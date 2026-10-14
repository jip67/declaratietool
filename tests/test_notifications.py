from datetime import timedelta

from sqlalchemy import select

from app import intake, mailer, notifications, reminders, workflow
from app.models import Claim, Status, User, utcnow
from app.routes import auth

from .conftest import jpeg_bytes, login
from .test_workflow import make_mail


def switch_on(db, *kinds, who="boekhouder@example.org", days=None):
    user = db.scalar(select(User).where(User.email == who))
    notifications.save(user, {kind: True for kind in kinds}, days)
    db.commit()


def sent_to_admin(subject_part=""):
    return [m for m in mailer.outbox if m["To"] == "boekhouder@example.org" and subject_part in m["Subject"]]


def test_all_off_by_default(db, client, staff):
    assert not any(notifications.load(staff["treasurer"]).values())
    assert set(notifications.load(staff["treasurer"])) == set(notifications.KINDS)
    # Bestuursleden zonder beheerrol krijgen de beheermeldingen niet te zien.
    assert set(notifications.load(staff["chair"])) == set(notifications.STAFF_KINDS)
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


def test_settings_page_per_user(db, client, staff):
    login(client, "voorzitter@example.org")
    page = client.get("/portal/notifications")
    assert page.status_code == 200
    assert 'name="new_claim"' in page.text and 'name="login"' not in page.text
    # Een bestuurslid zonder beheerrol kan de beheermeldingen niet aanzetten.
    r = client.post("/portal/notifications", data={"status": "on", "login": "on", "overdue": "on", "overdue_days": "5"},
                    follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    chair, treasurer = staff["chair"], staff["treasurer"]
    assert notifications.load(chair) == {"new_claim": False, "status": True, "overdue": True}
    assert chair.notify_overdue_days == 5
    # De instelling is persoonlijk: de beheerder heeft niets aan staan.
    assert not any(notifications.load(treasurer).values())
    client.post("/logout")
    login(client, "boekhouder@example.org")
    assert 'name="login"' in client.get("/portal/notifications").text
    client.post("/portal/notifications", data={"login": "on", "mail": "on", "overdue_days": "abc"})
    db.expire_all()
    assert notifications.load(treasurer)["login"] and notifications.load(treasurer)["mail"]
    assert treasurer.notify_overdue_days == notifications.DEFAULT_OVERDUE_DAYS


def test_settings_page_not_for_members(db, client, staff):
    from app.security import hash_password

    db.add(User(email="lid@example.org", name="Lid", password_hash=hash_password("geheim12345"), roles="member"))
    db.commit()
    login(client, "lid@example.org")
    assert client.get("/portal/notifications").status_code == 403
    assert client.post("/portal/notifications", data={"status": "on"}).status_code == 403


def test_overdue_days_bounds(staff):
    user = staff["chair"]
    notifications.save(user, {"overdue": True}, 0)
    assert user.notify_overdue_days == 1
    notifications.save(user, {"overdue": True}, 10_000)
    assert user.notify_overdue_days == notifications.MAX_OVERDUE_DAYS


def new_claim_by_mail(db):
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    return db.scalar(select(Claim).order_by(Claim.id.desc()))


def test_new_claim_notification(db, staff):
    switch_on(db, "new_claim", who="secretaris@example.org")
    claim = new_claim_by_mail(db)
    [msg] = [m for m in mailer.outbox if m["To"] == "secretaris@example.org"]
    assert claim.reference in msg["Subject"]
    body = msg.get_content()
    assert "piet@example.org" in body and f"/portal/claims/{claim.id}" in body
    # Wie het niet aanzette krijgt niets.
    assert not [m for m in mailer.outbox if m["To"] == "voorzitter@example.org"]


def test_new_claim_via_portal_not_to_creator(db, client, staff):
    switch_on(db, "new_claim", "status", who="secretaris@example.org")
    switch_on(db, "new_claim", "status", who="voorzitter@example.org")
    login(client, "secretaris@example.org")
    client.post("/portal/claims/new", data={
        "email": "piet@example.org", "name": "Piet", "iban": "NL91ABNA0417164300",
        "account_holder": "P. Jansen", "description": "Koffie", "amount": "12,50",
    }, files=[("files", ("bon.jpg", jpeg_bytes(), "image/jpeg"))])
    assert db.scalar(select(Claim)).status == Status.SUBMITTED.value
    assert not [m for m in mailer.outbox if m["To"] == "secretaris@example.org"]
    # De voorzitter krijgt één melding over de nieuwe declaratie, plus de taakmail, maar geen statusmelding.
    subjects = [m["Subject"] for m in mailer.outbox if m["To"] == "voorzitter@example.org"]
    assert len([s for s in subjects if "Nieuwe declaratie" in s]) == 1
    assert not [s for s in subjects if s.startswith("[") and "Nieuwe declaratie" not in s]


def test_status_notifications(db, staff):
    switch_on(db, "status", who="secretaris@example.org")
    switch_on(db, "status", who="voorzitter@example.org")
    claim = new_claim_by_mail(db)
    mailer.outbox.clear()
    workflow.complete_details(db, claim, iban="NL91ABNA0417164300", account_holder="P. Jansen",
                              description="Koffie", amount_cents=1250)
    # De voorzitter is nu aan zet en krijgt de taakmail, geen extra statusmelding.
    assert not [m for m in mailer.outbox if m["To"] == "voorzitter@example.org" and m["Subject"].startswith("[")]
    [msg] = [m for m in mailer.outbox if m["To"] == "secretaris@example.org"]
    assert claim.reference in msg["Subject"] and "Wacht op goedkeuring" in msg["Subject"]
    assert "Gegevens ingevuld" in msg.get_content()
    mailer.outbox.clear()
    workflow.approve(db, claim, staff["chair"])
    # Niet aan wie de stap zelf zette.
    assert not [m for m in mailer.outbox if m["To"] == "voorzitter@example.org" and m["Subject"].startswith("[")]
    [msg] = [m for m in mailer.outbox if m["To"] == "secretaris@example.org"]
    assert "Vera Voorzitter" in msg.get_content()
    mailer.outbox.clear()
    workflow.reject(db, claim, staff["treasurer"], "Dubbel ingediend")
    [msg] = [m for m in mailer.outbox if m["To"] == "secretaris@example.org"]
    assert "Dubbel ingediend" in msg.get_content()
    assert [m for m in mailer.outbox if m["To"] == "voorzitter@example.org" and m["Subject"].startswith("[")]


def make_overdue(db, days):
    claim = new_claim_by_mail(db)
    claim.status = Status.SUBMITTED.value
    claim.status_changed_at = utcnow() - timedelta(days=days)
    db.commit()
    mailer.outbox.clear()
    return claim


def overdue_mails(address):
    return [m for m in mailer.outbox if m["To"] == address and "open" in m["Subject"]]


def test_overdue_once_per_task(db, staff):
    switch_on(db, "overdue", who="secretaris@example.org", days=3)
    claim = make_overdue(db, 4)
    reminders.send_reminders(db)
    [msg] = overdue_mails("secretaris@example.org")
    assert "3 dagen" in msg["Subject"]
    body = msg.get_content()
    assert claim.reference in body and "Voorzitter" in body
    # De volgende dag niet nog eens.
    mailer.outbox.clear()
    reminders.send_reminders(db)
    assert overdue_mails("secretaris@example.org") == []
    # Na de volgende stap is het een nieuwe taak, die weer één keer gemeld mag worden.
    workflow.approve(db, claim, staff["chair"])
    claim.status_changed_at = utcnow() - timedelta(days=5)
    db.commit()
    mailer.outbox.clear()
    reminders.send_reminders(db)
    assert len(overdue_mails("secretaris@example.org")) == 1


def test_overdue_respects_days_and_choice(db, staff):
    switch_on(db, "overdue", who="secretaris@example.org", days=7)
    make_overdue(db, 4)
    reminders.send_reminders(db)
    assert overdue_mails("secretaris@example.org") == []
    # Wie het niet aanzette krijgt niets, ook al staat de taak lang open.
    make_overdue(db, 10)
    reminders.send_reminders(db)
    assert len(overdue_mails("secretaris@example.org")) == 1
    assert overdue_mails("voorzitter@example.org") == []
    assert overdue_mails("boekhouder@example.org") == []
