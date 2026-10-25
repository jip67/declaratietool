import re
from datetime import timedelta

from sqlalchemy import select

from app import mailer, reminders, workflow
from app.models import ApprovalLink, Claim, Event, Status, utcnow

from .conftest import login
from .test_claim_admin import make_claim

LINK = re.compile(r"http://testserver(/a/[\w-]+)")


def setup_claim(db, client, staff, enabled=True):
    staff["chair"].approve_by_link = enabled
    db.commit()
    mailer.outbox.clear()
    make_claim(client)
    client.post("/logout")
    return db.scalar(select(Claim))


def text(msg):
    return msg.get_body(("plain",)).get_content()


def chair_mails():
    return [text(m) for m in mailer.outbox if m["To"] == "voorzitter@example.org"]


def link_path(claim):
    return LINK.search(chair_mails()[0]).group(1)


def test_chair_approves_with_link_after_confirming(db, client, staff):
    claim = setup_claim(db, client, staff)
    path = link_path(claim)
    # In de database staat alleen de hash, niet het token zelf.
    assert path.removeprefix("/a/") not in db.scalar(select(ApprovalLink)).token_hash

    page = client.get(path)
    assert page.status_code == 200 and "Koffie" in page.text and "Goedkeuren en paraferen" in page.text
    assert client.get(path + f"/files/{claim.attachments[0].id}").status_code == 200
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value  # openen alleen keurt niets goed

    fp = re.search(r'name="fingerprint" value="(\w+)"', page.text).group(1)
    r = client.post(path, data={"fingerprint": fp}, follow_redirects=False)
    assert r.status_code == 303
    assert "Goedgekeurd en geparafeerd. Dank je wel!" in client.get(r.headers["location"]).text
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    assert claim.approved_by_id == staff["chair"].id
    assert all(a.stamped_path for a in claim.attachments)
    event = db.scalar(select(Event).where(Event.action == "approved"))
    assert event.note == "link" and event.user_id == staff["chair"].id
    assert db.scalar(select(ApprovalLink)).used_at is not None
    # De boekhouder krijgt zijn taak zoals altijd.
    assert any(m["To"] == "boekhouder@example.org" and "betaling" in text(m) for m in mailer.outbox)

    # Tweede keer: link is gebruikt, bijlagen niet meer via de link te zien.
    assert "al gebruikt" in client.get(path).text
    assert client.get(path + f"/files/{claim.attachments[0].id}").status_code == 404
    client.post(path, data={"fingerprint": fp})
    login(client, "boekhouder@example.org")
    assert "via link in e-mail" in client.get(f"/portal/claims/{claim.id}").text


def test_no_link_unless_enabled(db, client, staff):
    claim = setup_claim(db, client, staff, enabled=False)
    assert chair_mails() and not any("/a/" in body for body in chair_mails())
    assert db.scalar(select(ApprovalLink)) is None


def test_unknown_token_is_404(client, staff):
    assert client.get("/a/onzin").status_code == 404
    assert client.post("/a/onzin", data={"fingerprint": "x"}).status_code == 404


def test_link_stops_working_when_disabled_or_expired(db, client, staff):
    claim = setup_claim(db, client, staff)
    path = link_path(claim)
    staff["chair"].approve_by_link = False
    db.commit()
    assert "staat niet (meer) aan" in client.get(path).text
    client.post(path, data={"fingerprint": "x"})
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value

    staff["chair"].approve_by_link = True
    link = db.scalar(select(ApprovalLink))
    link.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert "verlopen" in client.get(path).text


def test_link_only_for_chair_role(db, client, staff):
    claim = setup_claim(db, client, staff)
    path = link_path(claim)
    staff["chair"].roles = "secretary"
    db.commit()
    assert "staat niet (meer) aan" in client.get(path).text


def test_old_link_invalid_after_undo(db, client, staff):
    claim = setup_claim(db, client, staff)
    path = link_path(claim)
    workflow.approve(db, claim, staff["chair"])
    workflow.undo(db, claim, staff["chair"])
    db.commit()
    assert claim.status == Status.SUBMITTED.value
    assert "wacht niet (meer)" in client.get(path).text
    # Na het ongedaan maken is er een nieuwe mail met een nieuwe, werkende link.
    new_path = LINK.findall("".join(chair_mails()))[-1]
    assert new_path != path and "Goedkeuren en paraferen" in client.get(new_path).text


def test_changed_details_need_a_second_look(db, client, staff):
    claim = setup_claim(db, client, staff)
    path = link_path(claim)
    fp = re.search(r'name="fingerprint" value="(\w+)"', client.get(path).text).group(1)
    claim.amount_cents = 99900
    db.commit()
    r = client.post(path, data={"fingerprint": fp})
    assert r.status_code == 409 and "gewijzigd" in r.text and "999,00" in r.text
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value


def test_reminder_contains_fresh_link(db, client, staff):
    claim = setup_claim(db, client, staff)
    claim.status_changed_at = utcnow() - timedelta(days=1)
    db.commit()
    mailer.outbox.clear()
    reminders.send_reminders(db)
    db.commit()
    path = LINK.search(chair_mails()[0]).group(1)
    # Herinnering voor een status van gisteren: link is gemaakt na de statuswijziging en dus geldig.
    assert "Goedkeuren en paraferen" in client.get(path).text


def test_admin_enables_setting(db, client, staff):
    login(client, "boekhouder@example.org")
    chair = staff["chair"]
    assert "goedkeuren via een link" in client.get(f"/portal/users/{chair.id}").text
    client.post(
        f"/portal/users/{chair.id}",
        data={"name": chair.name, "email": chair.email, "language": "nl", "roles": ["chair"],
              "active": "true", "approve_by_link": "true"},
    )
    db.expire_all()
    assert chair.approve_by_link
