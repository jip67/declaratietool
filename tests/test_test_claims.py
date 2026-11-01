"""Testdeclaraties: de beheerder loopt het hele proces zelf door, zonder dat de anderen er iets van merken."""

import re
from datetime import timedelta

from sqlalchemy import select

from app import intake, mailer, notifications, reminders
from app.models import Claim, Status, User, utcnow

from .conftest import SIGNATURE, jpeg_bytes, login
from .test_workflow import IBAN, make_mail

ADMIN = "boekhouder@example.org"  # Bob: boekhouder en beheerder
OTHERS = ("voorzitter@example.org", "secretaris@example.org")
LINK = re.compile(r"http://testserver(/a/[\w-]+)")


def text(msg):
    return msg.get_body(("plain",)).get_content()


def to(address):
    return [m for m in mailer.outbox if address in m["To"]]


def everyone_wants_everything(db):
    for user in db.scalars(select(User)):
        notifications.save(user, {k: True for k in notifications.KINDS}, overdue_days=1)
    db.commit()


def fill_in(client, claim):
    r = client.post(f"/c/{claim.token}", data={"iban": IBAN, "account_holder": "B. Boekhouder",
                                                "description": "Test", "amount": "1,00"}, follow_redirects=False)
    assert r.status_code == 303


def test_mail_with_subject_proces_test_runs_whole_flow_for_admin_only(db, client, staff):
    everyone_wants_everything(db)
    result = intake.process_message(db, make_mail([], sender=f"Bob <{ADMIN}>", subject="Proces  Test"))
    assert result.startswith("created:TEST-")
    claim = db.scalar(select(Claim))
    assert claim.is_test and claim.test_user_id == staff["treasurer"].id
    # Zonder bijlage komt er een voorbeeldbon bij.
    assert [a.content_type for a in claim.attachments] == ["application/pdf"]
    assert f"/c/{claim.token}" in text(to(ADMIN)[0])

    fill_in(client, claim)
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value
    # De beheerder krijgt de taak van de voorzitter, met goedkeurlink, ook al heeft hij die rol niet.
    task = [text(m) for m in to(ADMIN) if "/a/" in text(m)]
    assert task

    login(client, ADMIN)
    page = client.get(f"/portal/claims/{claim.id}")
    assert 'value="approve"' in page.text and "Testdeclaratie" in page.text
    assert client.get("/badge").json()["count"] == 1
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "approve", "signature": SIGNATURE})
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "prepare"})
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "pay"})
    db.expire_all()
    assert claim.status == Status.PAID.value
    assert all(a.stamped_path for a in claim.attachments)
    assert claim.approved_by_id == claim.prepared_by_id == claim.paid_by_id == staff["treasurer"].id

    # De anderen kregen niets: geen taak, geen melding over de nieuwe declaratie of statuswijziging.
    for address in OTHERS:
        assert to(address) == []


def test_approve_link_works_for_test_claim(db, client, staff):
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())], sender=ADMIN, subject="proces test"))
    claim = db.scalar(select(Claim))
    fill_in(client, claim)
    path = LINK.search(next(text(m) for m in to(ADMIN) if "/a/" in text(m))).group(1)
    page = client.get(path)
    fp = re.search(r'name="fingerprint" value="(\w+)"', page.text).group(1)
    client.post(path, data={"fingerprint": fp, "signature": SIGNATURE})
    db.expire_all()
    assert claim.status == Status.APPROVED.value


def test_others_do_not_see_test_claims(db, client, staff):
    intake.process_message(db, make_mail([], sender=ADMIN, subject="proces test"))
    claim = db.scalar(select(Claim))
    fill_in(client, claim)
    login(client, "voorzitter@example.org")
    assert claim.reference not in client.get("/portal?view=all").text
    assert claim.reference not in client.get("/portal?view=mine").text
    assert client.get(f"/portal/claims/{claim.id}").status_code == 404
    assert client.get("/badge").json()["count"] == 0
    # Ook de echte voorzitter kan hem niet goedkeuren.
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "approve", "signature": SIGNATURE})
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value


def test_reminders_and_overdue_only_go_to_admin(db, staff):
    everyone_wants_everything(db)
    intake.process_message(db, make_mail([], sender=ADMIN, subject="proces test"))
    claim = db.scalar(select(Claim))
    claim.status = Status.SUBMITTED.value
    claim.status_changed_at = utcnow() - timedelta(days=2)
    db.commit()
    mailer.outbox.clear()
    reminders.send_reminders(db)
    assert to(ADMIN)
    for address in OTHERS:
        assert to(address) == []


def test_subject_from_non_admin_is_a_normal_claim(db, staff):
    assert intake.process_message(db, make_mail([], sender="voorzitter@example.org", subject="proces test")) \
        == "rejected:no_attachment"
    result = intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())], subject="proces test"))
    claim = db.scalar(select(Claim))
    assert result.startswith("created:D") and not claim.is_test


def test_test_claim_does_not_use_a_real_reference(db, staff):
    intake.process_message(db, make_mail([], sender=ADMIN, subject="proces test"))
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    refs = sorted(c.reference for c in db.scalars(select(Claim)))
    year = utcnow().year
    assert refs == [f"D{year}-0001", f"TEST-D{year}-0001"]


def test_portal_button_and_delete_all(db, client, staff):
    login(client, ADMIN)
    assert "Testdeclaratie maken" in client.get("/portal/claims/new").text
    r = client.post("/portal/test-claims", follow_redirects=False)
    assert r.status_code == 303
    client.post("/portal/test-claims", files={"files": ("bon.jpg", jpeg_bytes(), "image/jpeg")})
    claims = db.scalars(select(Claim)).all()
    assert len(claims) == 2 and all(c.is_test for c in claims)
    assert to(ADMIN)  # bevestiging met de link, zoals een indiener die krijgt
    assert "2 testdeclaratie" in client.get("/portal").text

    assert client.post("/portal/test-claims/delete", follow_redirects=False).status_code == 303
    assert len(db.scalars(select(Claim)).all()) == 2  # zonder vinkje niets gewist
    r = client.post("/portal/test-claims/delete", data={"confirm": "yes"})
    assert "2 testdeclaratie(s) gewist" in r.text
    db.expire_all()
    assert db.scalars(select(Claim)).all() == []


def test_only_admins_can_create_test_claims(db, client, staff):
    login(client, "voorzitter@example.org")
    assert "Testdeclaratie maken" not in client.get("/portal/claims/new").text
    assert client.post("/portal/test-claims").status_code == 403


def test_deleting_admin_removes_their_test_claims(db, client, staff):
    from app.security import hash_password

    other = User(email="beheer2@example.org", name="Tweede Beheerder", password_hash=hash_password("geheim12345"), roles="admin")
    db.add(other)
    db.commit()
    intake.process_message(db, make_mail([], sender=other.email, subject="proces test"))
    assert db.scalar(select(Claim)).is_test
    login(client, ADMIN)
    client.post(f"/portal/users/{other.id}/delete")
    db.expire_all()
    assert db.scalars(select(Claim)).all() == []
