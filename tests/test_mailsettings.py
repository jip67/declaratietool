import smtplib

from sqlalchemy import select

from app import mailconfig, mailer
from app.models import KeyValue

from .conftest import login


def form(**overrides):
    data = {
        "smtp_host": "smtp.vereniging.nl", "smtp_port": "587", "smtp_user": "bot@vereniging.nl",
        "smtp_password": "smtp-geheim", "smtp_starttls": "on", "mail_from": "declaraties@vereniging.nl",
        "imap_host": "imap.vereniging.nl", "imap_port": "993", "imap_user": "declaraties@vereniging.nl",
        "imap_password": "imap-geheim", "imap_folder": "INBOX", "action": "save",
    }
    data.update(overrides)
    return data


class FakeSMTP:
    instances = []
    fail_login = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.sent, self.calls = host, port, [], []
        FakeSMTP.instances.append(self)

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        self.calls.append(("login", user, password))

    def noop(self):
        self.calls.append("noop")

    def send_message(self, msg):
        self.sent.append(msg)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_only_admin_sees_mail_settings(client, staff):
    login(client, "voorzitter@example.org")
    assert client.get("/portal/mail").status_code == 403
    assert client.post("/portal/mail", data=form()).status_code == 403


def test_save_overrides_env_and_encrypts_passwords(db, client, staff):
    login(client, "boekhouder@example.org")
    page = client.get("/portal/mail")
    assert page.status_code == 200 and "(uit .env)" in page.text
    r = client.post("/portal/mail", data=form(), follow_redirects=False)
    assert r.status_code == 303

    stored = {kv.key: kv.value for kv in db.scalars(select(KeyValue))}
    assert stored["mail.smtp_host"] == "smtp.vereniging.nl"
    assert "smtp-geheim" not in stored["mail.smtp_password"]
    config = mailconfig.load(db)
    assert config.smtp_host == "smtp.vereniging.nl" and config.smtp_password == "smtp-geheim"
    assert config.imap_password == "imap-geheim" and config.smtp_starttls and not config.smtp_ssl

    page = client.get("/portal/mail")
    assert "smtp.vereniging.nl" in page.text
    assert "smtp-geheim" not in page.text and "imap-geheim" not in page.text


def test_empty_password_keeps_saved_one(db, client, staff):
    login(client, "boekhouder@example.org")
    client.post("/portal/mail", data=form())
    client.post("/portal/mail", data=form(smtp_password="", imap_password="", smtp_host="smtp2.vereniging.nl"))
    config = mailconfig.load(db)
    assert config.smtp_host == "smtp2.vereniging.nl" and config.smtp_password == "smtp-geheim"
    client.post("/portal/mail", data=form(smtp_password="", imap_password="", clear_passwords="on"))
    assert mailconfig.load(db).smtp_password == ""


def test_invalid_port_is_refused(db, client, staff):
    login(client, "boekhouder@example.org")
    r = client.post("/portal/mail", data=form(smtp_port="99999"))
    assert r.status_code == 422
    assert db.get(KeyValue, "mail.smtp_host") is None


def test_reset_returns_to_env(db, client, staff, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.uit-env.nl")
    mailconfig.get_settings.cache_clear()
    login(client, "boekhouder@example.org")
    client.post("/portal/mail", data=form())
    assert mailconfig.load(db).smtp_host == "smtp.vereniging.nl"
    client.post("/portal/mail", data={"action": "reset"})
    config = mailconfig.load(db)
    assert config.smtp_host == "smtp.uit-env.nl" and not config.from_db


def test_changed_secret_key_falls_back_to_env(db, client, staff, monkeypatch):
    login(client, "boekhouder@example.org")
    client.post("/portal/mail", data=form())
    monkeypatch.setenv("SECRET_KEY", "een-andere-sleutel-van-minstens-32-tekens")
    mailconfig.get_settings.cache_clear()
    config = mailconfig.load(db)
    assert config.smtp_host == "smtp.vereniging.nl" and config.smtp_password == ""


def test_mailer_uses_saved_settings_without_restart(db, client, staff, monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    login(client, "boekhouder@example.org")
    client.post("/portal/mail", data=form())
    mailer.send(mailer.Mail(to=["iemand@example.org"], subject="Hallo", body="Test"))
    server = FakeSMTP.instances[-1]
    assert (server.host, server.port) == ("smtp.vereniging.nl", 587)
    assert ("login", "bot@vereniging.nl", "smtp-geheim") in server.calls
    assert server.sent[0]["From"].addresses[0].addr_spec == "declaraties@vereniging.nl"


def test_smtp_test_button_uses_form_and_saved_password(db, client, staff, monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_login = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    login(client, "boekhouder@example.org")
    client.post("/portal/mail", data=form())
    r = client.post("/portal/mail", data=form(action="test_smtp", smtp_password="", smtp_host="smtp.nieuw.nl"))
    assert r.status_code == 200 and "SMTP-verbinding gelukt" in r.text
    assert FakeSMTP.instances[-1].host == "smtp.nieuw.nl"
    assert ("login", "bot@vereniging.nl", "smtp-geheim") in FakeSMTP.instances[-1].calls
    # Testen slaat niets op.
    assert mailconfig.load(db).smtp_host == "smtp.vereniging.nl"

    FakeSMTP.fail_login = True
    try:
        r = client.post("/portal/mail", data=form(action="test_smtp", smtp_password="fout-wachtwoord"))
    finally:
        FakeSMTP.fail_login = False
    assert "SMTP-verbinding mislukt" in r.text and "Authentication failed" in r.text
    assert "fout-wachtwoord" not in r.text


def test_imap_test_button(client, staff, monkeypatch):
    class FakeIMAP:
        def __init__(self, host, port, timeout=None):
            self.host = host

        def login(self, user, password):
            assert password == "imap-geheim"

        def select(self, folder):
            return ("OK", [b"3"])

        def search(self, charset, criterion):
            return ("OK", [b"1 2"])

        def logout(self):
            pass

    monkeypatch.setattr(mailconfig.imaplib, "IMAP4_SSL", FakeIMAP)
    login(client, "boekhouder@example.org")
    r = client.post("/portal/mail", data=form(action="test_imap"))
    assert "IMAP-verbinding gelukt" in r.text and "2 ongelezen" in r.text
    r = client.post("/portal/mail", data=form(action="test_imap", imap_host=""))
    assert "Vul eerst een IMAP-server in" in r.text


def test_help_shows_mailbox_from_saved_settings(client, staff):
    login(client, "boekhouder@example.org")
    client.post("/portal/mail", data=form())
    assert "declaraties@vereniging.nl" in client.get("/help").text
