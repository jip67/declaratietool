from datetime import timedelta

from sqlalchemy import select

from app import activity, intake
from app.models import IncomingMail, LoginAttempt, User, utcnow
from app.security import hash_password

from .conftest import jpeg_bytes, login
from .test_workflow import make_mail


def test_logins_are_recorded_with_reason(db, client, staff):
    client.post("/login", data={"email": "voorzitter@example.org", "password": "fout"}, headers={"User-Agent": "TestBrowser"})
    client.post("/login", data={"email": "onbekend@example.org", "password": "fout"})
    login(client, "voorzitter@example.org")
    rows = db.scalars(select(LoginAttempt).order_by(LoginAttempt.id)).all()
    assert [(r.email, r.success, r.reason) for r in rows] == [
        ("voorzitter@example.org", False, "wrong_password"),
        ("onbekend@example.org", False, "unknown_user"),
        ("voorzitter@example.org", True, ""),
    ]
    assert rows[0].user_agent == "TestBrowser"
    assert rows[0].ip
    assert rows[2].user_id == staff["chair"].id


def test_inactive_and_locked_are_recorded(db, client, staff):
    db.add(User(email="oud@example.org", name="Oud", password_hash=hash_password("geheim12345"), active=False))
    db.commit()
    client.post("/login", data={"email": "oud@example.org", "password": "geheim12345"})
    for _ in range(6):
        client.post("/login", data={"email": "voorzitter@example.org", "password": "fout"})
    reasons = [r.reason for r in db.scalars(select(LoginAttempt).order_by(LoginAttempt.id))]
    assert reasons[0] == "inactive"
    assert reasons[-1] == "locked"


def test_incoming_mail_is_recorded(db):
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    intake.process_message(db, make_mail([], subject="Vergeten"))
    rows = db.scalars(select(IncomingMail).order_by(IncomingMail.id)).all()
    assert rows[0].sender == "Piet Jansen <piet@example.org>"
    assert rows[0].subject == "Boodschappen feest"
    assert rows[0].attachments == 1
    assert rows[0].result.startswith("created:") and rows[0].claim is not None
    assert (rows[1].subject, rows[1].result, rows[1].claim_id) == ("Vergeten", "rejected:no_attachment", None)


def test_failed_mail_recorded_once_per_day(db):
    raw = make_mail([], subject="Kapot")
    intake._record_failure(db, raw)
    intake._record_failure(db, raw)
    rows = db.scalars(select(IncomingMail)).all()
    assert [(r.subject, r.result) for r in rows] == [("Kapot", "error")]


def test_only_admin_sees_log(client, staff):
    login(client, "voorzitter@example.org")
    assert client.get("/portal/log").status_code == 403
    assert "/portal/log" not in client.get("/portal").text


def test_log_page_tabs_search_and_paging(db, client, staff):
    client.post("/login", data={"email": "indringer@example.org", "password": "fout"})
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    login(client, "boekhouder@example.org")
    assert "/portal/log" in client.get("/portal").text

    r = client.get("/portal/log")
    assert "boekhouder@example.org" in r.text and "indringer@example.org" not in r.text
    r = client.get("/portal/log?tab=failed")
    assert "indringer@example.org" in r.text and "Onbekend e-mailadres" in r.text
    r = client.get("/portal/log?tab=mails")
    assert "Boodschappen feest" in r.text and "Declaratie aangemaakt" in r.text
    r = client.get("/portal/log?tab=mails&q=niets-gevonden")
    assert "Boodschappen feest" not in r.text

    db.add_all(LoginAttempt(email=f"x{i}@example.org", success=False, reason="unknown_user") for i in range(60))
    db.commit()
    r = client.get("/portal/log?tab=failed")
    assert "Pagina 1 van 2" in r.text
    r = client.get("/portal/log?tab=failed&page=2")
    assert "Pagina 2 van 2" in r.text and "indringer@example.org" in r.text


def test_purge_removes_old_entries(db, monkeypatch):
    old = utcnow() - timedelta(days=91)
    db.add_all([
        LoginAttempt(email="oud@example.org", at=old), LoginAttempt(email="nieuw@example.org"),
        IncomingMail(sender="oud", at=old), IncomingMail(sender="nieuw"),
    ])
    db.commit()
    assert activity.purge(db) == 2
    assert [r.email for r in db.scalars(select(LoginAttempt))] == ["nieuw@example.org"]
    assert [r.sender for r in db.scalars(select(IncomingMail))] == ["nieuw"]

    monkeypatch.setenv("LOG_RETENTION_DAYS", "0")
    from app.config import get_settings

    get_settings.cache_clear()
    db.add(LoginAttempt(email="oud@example.org", at=old))
    db.commit()
    assert activity.purge(db) == 0
