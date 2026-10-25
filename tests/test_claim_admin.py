from pathlib import Path

from sqlalchemy import select

from app import mailer, storage
from app.models import Attachment, Claim, Comment, Event, IncomingMail, Status, Submitter
from app.security import hash_password
from app.models import User

from .conftest import jpeg_bytes, login, pdf_bytes

IBAN = "NL91ABNA0417164300"


def make_claim(client, email="boekhouder@example.org"):
    login(client, email)
    client.post(
        "/portal/claims/new",
        data={"email": "indiener@example.org", "name": "Ina Indiener", "iban": IBAN,
              "account_holder": "I. Indiener", "description": "Koffie", "amount": "8,50"},
        files=[("files", ("bon.pdf", pdf_bytes(), "application/pdf"))],
    )


def test_admin_edits_claim(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    page = client.get(f"/portal/claims/{claim.id}/edit")
    assert page.status_code == 200 and "Koffie" in page.text
    r = client.post(
        f"/portal/claims/{claim.id}/edit",
        data={"name": "Ina", "description": "Thee", "amount": "12,00", "iban": IBAN, "account_holder": "Ina I."},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.refresh(claim)
    assert (claim.description, claim.amount_cents, claim.account_holder) == ("Thee", 1200, "Ina I.")
    assert claim.status == Status.SUBMITTED.value
    assert db.scalar(select(Event).where(Event.action == "edited")) is not None


def test_edit_validates(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    r = client.post(f"/portal/claims/{claim.id}/edit",
                    data={"description": "Thee", "amount": "abc", "iban": "NL00", "account_holder": "x"})
    assert r.status_code == 422
    db.refresh(claim)
    assert claim.description == "Koffie"


def test_only_admin_may_edit_or_delete(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    client.cookies.clear()
    login(client, "voorzitter@example.org")
    assert "/edit" not in client.get(f"/portal/claims/{claim.id}").text
    assert client.get(f"/portal/claims/{claim.id}/edit").status_code == 403
    assert client.post(f"/portal/claims/{claim.id}/edit", data={"description": "x"}).status_code == 403
    assert client.post(f"/portal/claims/{claim.id}/delete", data={"confirm": "yes"}).status_code == 403
    assert db.get(Claim, claim.id) is not None


def test_admin_deletes_claim_and_files(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    claim_id = claim.id
    login(client, "voorzitter@example.org")
    client.post(f"/portal/claims/{claim_id}/action", data={"action": "approve"})
    login(client, "boekhouder@example.org")
    db.refresh(claim)
    att = claim.attachments[0]
    original, stamped = storage.absolute(att.stored_path), storage.absolute(att.stamped_path)
    assert original.exists() and stamped.exists()
    db.add(IncomingMail(sender="indiener@example.org", subject="bon", result="created", claim_id=claim_id))
    db.commit()
    client.post(f"/portal/claims/{claim_id}/comments", data={"text": "Even nagaan"})

    # Zonder bevestiging gebeurt er niets.
    r = client.post(f"/portal/claims/{claim_id}/delete", follow_redirects=False)
    assert r.status_code == 303 and "error=delete_confirm" in r.headers["location"]
    db.expire_all()
    assert db.get(Claim, claim_id) is not None

    r = client.post(f"/portal/claims/{claim_id}/delete", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Claim, claim_id) is None
    assert db.scalar(select(Comment)) is None
    assert db.scalar(select(IncomingMail)).claim_id is None
    assert not original.exists() and not stamped.exists()
    assert not (Path(storage.upload_root()) / str(claim_id)).exists()


def test_internal_comments_only_for_staff(db, client, staff):
    db.add(User(email="indiener@example.org", name="Ina", password_hash=hash_password("geheim12345"), roles="member"))
    db.commit()
    make_claim(client, "voorzitter@example.org")
    claim = db.scalar(select(Claim))
    r = client.post(f"/portal/claims/{claim.id}/comments", data={"text": "Geheime notitie"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(f"/portal/claims/{claim.id}").text
    assert "Geheime notitie" in page and "niet zichtbaar voor indiener" in page and "Vera Voorzitter" in page

    # Leeg mag niet.
    r = client.post(f"/portal/claims/{claim.id}/comments", data={"text": "  "}, follow_redirects=False)
    assert "error=comment_required" in r.headers["location"]
    assert len(db.scalars(select(Comment)).all()) == 1

    # De indiener ziet hem niet: niet via de persoonlijke link, niet als gebruiker, niet in mails.
    assert "Geheime notitie" not in client.get(f"/c/{claim.token}").text
    assert all("Geheime notitie" not in str(m) for m in mailer.outbox)
    client.cookies.clear()
    login(client, "indiener@example.org")
    page = client.get(f"/portal/claims/{claim.id}")
    assert page.status_code == 200 and "Geheime notitie" not in page.text
    assert client.post(f"/portal/claims/{claim.id}/comments", data={"text": "x"}).status_code == 403


def test_dashboard_shows_comment_icon_for_staff_only(db, client, staff):
    db.add(User(email="indiener@example.org", name="Ina", password_hash=hash_password("geheim12345"), roles="member"))
    db.commit()
    make_claim(client)
    claim = db.scalar(select(Claim))
    assert "comment-flag" not in client.get("/portal").text
    client.post(f"/portal/claims/{claim.id}/comments", data={"text": "Eerste"})
    client.post(f"/portal/claims/{claim.id}/comments", data={"text": "Bon nagevraagd"})
    page = client.get("/portal").text
    assert "comment-flag" in page and "2 interne opmerking(en)" in page and "Bon nagevraagd" in page
    client.cookies.clear()
    login(client, "indiener@example.org")
    page = client.get("/portal").text
    assert claim.reference in page and "comment-flag" not in page and "Bon nagevraagd" not in page


def test_admin_fixes_submitter_email_typo(db, client, staff):
    login(client, "boekhouder@example.org")
    client.post(
        "/portal/claims/new",
        data={"email": "ina@exmaple.org", "name": "Ina Indienr", "iban": IBAN,
              "account_holder": "I. Indiener", "description": "Koffie", "amount": "8,50"},
        files=[("files", ("bon.pdf", pdf_bytes(), "application/pdf"))],
    )
    claim = db.scalar(select(Claim))
    mailer.outbox.clear()
    r = client.post(
        f"/portal/claims/{claim.id}/edit",
        data={"name": "Ina Indiener", "email": "Ina@Example.org", "resend": "yes", "description": "Koffie",
              "amount": "8,50", "iban": IBAN, "account_holder": "I. Indiener"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.expire_all()
    claim = db.get(Claim, claim.id)
    assert (claim.submitter.email, claim.submitter.name) == ("ina@example.org", "Ina Indiener")
    assert claim.submitter.iban == IBAN
    # Het verkeerde adres wordt vergeten; de indiener krijgt de stand op het goede adres.
    assert db.scalar(select(Submitter).where(Submitter.email == "ina@exmaple.org")) is None
    assert [m["To"] for m in mailer.outbox] == ["ina@example.org"]
    event = db.scalar(select(Event).where(Event.action == "edited"))
    assert event.note == "name,email"
    page = client.get(f"/portal/claims/{claim.id}").text
    assert "naam, e-mailadres" in page

    r = client.post(f"/portal/claims/{claim.id}/edit",
                    data={"email": "geen-adres", "description": "Koffie", "amount": "8,50", "iban": IBAN,
                          "account_holder": "I. Indiener"})
    assert r.status_code == 422


def test_email_change_keeps_other_claims_of_old_address(db, client, staff):
    make_claim(client)
    make_claim(client)
    first, second = db.scalars(select(Claim).order_by(Claim.id)).all()
    client.post(f"/portal/claims/{first.id}/edit",
                data={"email": "ander@example.org", "description": "Koffie", "amount": "8,50", "iban": IBAN,
                      "account_holder": "I. Indiener"})
    db.expire_all()
    assert db.get(Claim, first.id).submitter.email == "ander@example.org"
    assert db.get(Claim, second.id).submitter.email == "indiener@example.org"


def test_admin_replaces_attachment_before_approval(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    att = claim.attachments[0]
    old = storage.absolute(att.stored_path)
    r = client.post(f"/portal/claims/{claim.id}/attachments/{att.id}/replace",
                    files={"file": ("getekend.jpg", jpeg_bytes(), "image/jpeg")}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    att = db.get(Attachment, att.id)
    assert (att.original_filename, att.content_type, att.stamped_path) == ("getekend.jpg", "image/jpeg", None)
    assert storage.absolute(att.stored_path).exists() and not old.exists()
    event = db.scalar(select(Event).where(Event.action == "attachment_replaced"))
    assert event.note == "bon.pdf → getekend.jpg"
    assert "Bijlage vervangen door beheerder" in client.get(f"/portal/claims/{claim.id}").text


def test_replaced_attachment_keeps_approval_stamp(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    login(client, "voorzitter@example.org")
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "approve"})
    # Alleen de beheerder mag vervangen.
    att = db.scalar(select(Attachment))
    r = client.post(f"/portal/claims/{claim.id}/attachments/{att.id}/replace",
                    files={"file": ("getekend.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code == 403
    login(client, "boekhouder@example.org")
    db.expire_all()
    att = db.scalar(select(Attachment))
    old_stamped = storage.absolute(att.stamped_path)
    client.post(f"/portal/claims/{claim.id}/attachments/{att.id}/replace",
                files={"file": ("getekend.pdf", pdf_bytes(), "application/pdf")})
    db.expire_all()
    att = db.get(Attachment, att.id)
    claim = db.get(Claim, claim.id)
    assert claim.status == Status.APPROVED.value
    assert att.stamped_path and storage.absolute(att.stamped_path).exists() and not old_stamped.exists()
    from pypdf import PdfReader
    text = PdfReader(storage.absolute(att.stamped_path)).pages[0].extract_text()
    assert "Vera Voorzitter" in text and claim.reference in text


def test_replace_rejects_wrong_file(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    att = claim.attachments[0]
    r = client.post(f"/portal/claims/{claim.id}/attachments/{att.id}/replace",
                    files={"file": ("virus.exe", b"MZ", "application/octet-stream")}, follow_redirects=False)
    assert "error=file_type" in r.headers["location"]
    db.refresh(att)
    assert att.original_filename == "bon.pdf"
