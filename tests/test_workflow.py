from email.message import EmailMessage

from sqlalchemy import select

from app import intake, mailer, reminders
from app.models import Claim, KeyValue, Status, Submitter
from app.storage import absolute

from .conftest import jpeg_bytes, login, pdf_bytes

IBAN = "NL91ABNA0417164300"


def make_mail(attachments, sender="Piet Jansen <piet@example.org>", subject="Boodschappen feest"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "declaraties@example.org"
    msg["Subject"] = subject
    msg.set_content("Zie bijlage")
    for name, ctype, data in attachments:
        maintype, subtype = ctype.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


def sent_to(address):
    return [m for m in mailer.outbox if address in m["To"]]


def test_mail_without_attachment_is_refused(db):
    assert intake.process_message(db, make_mail([])) == "rejected:no_attachment"
    assert db.scalar(select(Claim)) is None
    assert "geen bijlage" in sent_to("piet@example.org")[0]["Subject"]


def test_auto_reply_is_ignored(db):
    raw = make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())])
    raw = b"Auto-Submitted: auto-replied\r\n" + raw
    assert intake.process_message(db, raw) == "ignored:automatic"


def test_full_flow(db, client, staff):
    # 1. Mail met bon komt binnen -> bevestiging met link
    result = intake.process_message(
        db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes()), ("factuur.pdf", "application/pdf", pdf_bytes())])
    )
    assert result.startswith("created:")
    claim = db.scalar(select(Claim))
    assert claim.status == Status.RECEIVED.value
    assert len(claim.attachments) == 2
    confirmation = sent_to("piet@example.org")[-1]
    assert f"/c/{claim.token}" in confirmation.get_content()

    # 2. Indiener vult gegevens aan
    page = client.get(f"/c/{claim.token}")
    assert page.status_code == 200 and claim.reference in page.text
    bad = client.post(f"/c/{claim.token}", data={"iban": "NL00", "account_holder": "", "description": "x", "amount": "abc"})
    assert bad.status_code == 422
    ok = client.post(
        f"/c/{claim.token}",
        data={"iban": IBAN, "account_holder": "P. Jansen", "description": "Boodschappen", "amount": "23,45", "remember": "true"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value
    assert claim.amount_cents == 2345
    assert db.scalar(select(Submitter)).iban == IBAN
    assert sent_to("voorzitter@example.org"), "voorzitter krijgt bericht"

    # Alleen de juiste rol mag de stap zetten
    login(client, "secretaris@example.org")
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "approve"})
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value

    # 3. Voorzitter keurt goed -> paraaf
    login(client, "voorzitter@example.org")
    mine = client.get("/portal?view=mine")
    assert claim.reference in mine.text
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "approve"})
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    for att in claim.attachments:
        assert att.stamped_path and absolute(att.stamped_path).exists()
    treasurer_mail = sent_to("boekhouder@example.org")[-1]
    assert len(list(treasurer_mail.iter_attachments())) == 2
    stamped = client.get(f"/portal/files/{claim.attachments[0].id}?stamped=1")
    assert stamped.headers["content-type"] == "application/pdf"

    # 4. Boekhouder zet betaling klaar
    login(client, "boekhouder@example.org")
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "prepare"})
    db.expire_all()
    assert claim.status == Status.PAYMENT_PREPARED.value
    assert sent_to("secretaris@example.org")

    # 5. Secretaris geeft akkoord
    login(client, "secretaris@example.org")
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "pay"})
    db.expire_all()
    assert claim.status == Status.PAID.value
    assert len(sent_to("piet@example.org")) == 5  # ontvangen + 4 statusupdates
    assert [e.action for e in claim.events] == ["created", "submitted", "approved", "payment_prepared", "paid"]

    # Volgende declaratie: rekeninggegevens zijn al ingevuld
    intake.process_message(db, make_mail([("bon2.jpg", "image/jpeg", jpeg_bytes())]))
    second = db.scalars(select(Claim).order_by(Claim.id.desc())).first()
    assert second.iban == IBAN and second.account_holder == "P. Jansen"
    assert second.reference != claim.reference


def test_staff_creates_claim_for_someone(db, client, staff):
    login(client, "boekhouder@example.org")
    r = client.post(
        "/portal/claims/new",
        data={"email": "anna@example.org", "name": "Anna", "iban": IBAN, "account_holder": "A. de Vries",
              "description": "Treinkaartje", "amount": "12,00"},
        files=[("files", ("kaartje.pdf", pdf_bytes(), "application/pdf"))],
        follow_redirects=False,
    )
    assert r.status_code == 303
    claim = db.scalar(select(Claim))
    assert claim.status == Status.SUBMITTED.value and claim.source == "portal"
    assert sent_to("voorzitter@example.org")


def test_reject(db, client, staff):
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    claim = db.scalar(select(Claim))
    login(client, "voorzitter@example.org")
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "reject", "reason": "Geen bon van de vereniging"})
    db.expire_all()
    assert claim.status == Status.REJECTED.value
    assert "Geen bon van de vereniging" in sent_to("piet@example.org")[-1].get_content()


def test_reminders(db, staff):
    from datetime import timedelta

    from app.models import utcnow

    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    claim = db.scalar(select(Claim))
    claim.status = Status.SUBMITTED.value
    claim.status_changed_at = utcnow() - timedelta(days=1)
    db.commit()
    mailer.outbox.clear()
    assert reminders.send_reminders(db) == 1
    assert "Herinnering" in sent_to("voorzitter@example.org")[0]["Subject"]


def test_reminders_run_once_per_day(db, monkeypatch):
    monkeypatch.setenv("REMINDER_HOUR", "0")
    from app.config import get_settings

    get_settings.cache_clear()
    assert reminders.run_if_due(db) is True
    assert reminders.run_if_due(db) is False
    assert db.get(KeyValue, reminders.LAST_RUN_KEY) is not None


def test_portal_requires_login(client):
    r = client.get("/portal", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_english(db, client):
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    claim = db.scalar(select(Claim))
    assert "Bank account" in client.get(f"/c/{claim.token}?lang=en").text


def test_login_lockout(client, staff):
    for _ in range(5):
        assert client.post("/login", data={"email": "voorzitter@example.org", "password": "fout"}).status_code == 401
    r = client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"})
    assert r.status_code == 429


def test_upload_page(db, client):
    from app.routes import public

    public._uploads.clear()
    r = client.post(
        "/indienen",
        data={"email": "Kees@Example.org", "name": "Kees"},
        files=[("files", ("bon.jpg", jpeg_bytes(), "image/jpeg"))],
    )
    assert r.status_code == 200 and "kees@example.org" in r.text
    claim = db.scalar(select(Claim))
    assert claim.source == "upload" and claim.status == Status.RECEIVED.value
    # De link staat alleen in de mail, niet op de pagina.
    assert claim.token not in r.text
    assert f"/c/{claim.token}" in sent_to("kees@example.org")[-1].get_content()


def test_upload_requires_file_and_blocks_bots(db, client):
    from app.routes import public

    public._uploads.clear()
    assert client.post("/indienen", data={"email": "a@b.nl"}).status_code == 422
    r = client.post("/indienen", data={"email": "a@b.nl", "website": "spam"},
                    files=[("files", ("bon.jpg", jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 200
    assert db.scalar(select(Claim)) is None
