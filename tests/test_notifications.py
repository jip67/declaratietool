from app import intake, mailer, notifications
from app.routes import auth

from .conftest import jpeg_bytes, login
from .test_workflow import make_mail


def switch_on(db, *kinds):
    notifications.save(db, {kind: True for kind in kinds})
    db.commit()


def sent_to_admin(subject_part=""):
    return [m for m in mailer.outbox if m["To"] == "boekhouder@example.org" and subject_part in m["Subject"]]


def test_all_off_by_default(db, client, staff):
    assert notifications.load(db) == {"login": False, "lockout": False, "mail": False}
    login(client, "voorzitter@example.org")
    for _ in range(6):
        client.post("/login", data={"email": "secretaris@example.org", "password": "fout"})
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    assert sent_to_admin("[") == []


def test_login_notification(db, client, staff):
    switch_on(db, "login")
    login(client, "voorzitter@example.org")
    [msg] = sent_to_admin("Vera Voorzitter")
    body = msg.get_content()
    assert "voorzitter@example.org" in body and "IP" in body
    # Alleen beheerders krijgen de melding.
    assert all(m["To"] == "boekhouder@example.org" for m in mailer.outbox)


def test_lockout_notified_once(db, client, staff):
    switch_on(db, "lockout")
    for _ in range(auth.MAX_ATTEMPTS + 3):
        client.post("/login", data={"email": "secretaris@example.org", "password": "fout"})
    [msg] = sent_to_admin("secretaris@example.org")
    assert "15" in msg.get_content()


def test_lockout_by_ip(db, client, staff):
    switch_on(db, "lockout")
    for i in range(auth.MAX_ATTEMPTS_PER_IP):
        client.post("/login", data={"email": f"x{i}@example.org", "password": "fout"})
    assert len(sent_to_admin("x")) == 1


def test_incoming_mail_notification(db, staff):
    switch_on(db, "mail")
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    [msg] = sent_to_admin("piet@example.org")
    assert "Boodschappen feest" in msg.get_content()


def test_automatic_mail_not_notified(db, staff):
    switch_on(db, "mail")
    raw = make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())])
    raw = b"Auto-Submitted: auto-replied\r\n" + raw
    assert intake.process_message(db, raw) == "ignored:automatic"
    assert sent_to_admin("[") == []


def test_settings_page_admin_only(db, client, staff):
    login(client, "voorzitter@example.org")
    assert client.get("/portal/notifications").status_code == 403
    assert client.post("/portal/notifications", data={"login": "on"}).status_code == 403
    client.post("/logout")
    login(client, "boekhouder@example.org")
    assert client.get("/portal/notifications").status_code == 200
    r = client.post("/portal/notifications", data={"login": "on", "mail": "on"}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert notifications.load(db) == {"login": True, "lockout": False, "mail": True}
    page = client.get("/portal/notifications").text
    assert "boekhouder@example.org" in page
