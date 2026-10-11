import re
import time
import time

from app import totp
from app.models import LoginAttempt, User
from tests.conftest import login


def test_totp_matches_rfc6238_vector():
    # RFC 6238, bijlage B (SHA-1), teruggebracht tot 6 cijfers.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.current_code(secret, now=59) == "287082"
    assert totp.current_code(secret, now=1111111109) == "081804"


def test_verify_window_and_replay():
    secret = totp.new_secret()
    now = 1_700_000_000
    code = totp.current_code(secret, now=now)
    step = totp.verify(secret, code, now=now)
    assert step == now // 30
    assert totp.verify(secret, code, now=now + 30) == step  # klok iets achter: nog goed
    assert totp.verify(secret, code, now=now + 120) is None
    assert totp.verify(secret, code, last_step=step, now=now) is None  # al gebruikt
    assert totp.verify(secret, "12345", now=now) is None


def test_recovery_codes_work_once():
    codes, stored = totp.new_recovery_codes()
    assert len(codes) == 10 and totp.recovery_codes_left(stored) == 10
    left = totp.use_recovery_code(stored, codes[0].upper().replace("-", " "))
    assert left is not None and totp.recovery_codes_left(left) == 9
    assert totp.use_recovery_code(left, codes[0]) is None


def _enable(client, db, email):
    login(client, email)
    page = client.get("/account/2fa")
    assert page.status_code == 200 and "data:image/svg+xml" in page.text
    secret = re.search(r'<code class="secret">([A-Z2-7 ]+)</code>', page.text).group(1).replace(" ", "")
    wrong = client.post("/account/2fa", data={"code": "000000" if totp.current_code(secret) != "000000" else "111111"})
    assert wrong.status_code == 422
    r = client.post("/account/2fa", data={"code": totp.current_code(secret)})
    assert r.status_code == 200
    codes = re.findall(r"<li><code>([a-z0-9]{5}-[a-z0-9]{5})</code></li>", r.text)
    assert len(codes) == 10
    user = db.query(User).filter_by(email=email).one()
    db.refresh(user)
    assert user.has_2fa and user.totp_secret == secret
    client.post("/logout")
    return secret, codes


def test_enable_and_login_with_code(client, db, staff):
    secret, _ = _enable(client, db, "voorzitter@example.org")

    r = client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"}, follow_redirects=False)
    assert r.headers["location"] == "/login/2fa"
    # Alleen het wachtwoord is niet genoeg.
    assert client.get("/portal", follow_redirects=False).headers["location"].startswith("/login")

    bad = client.post("/login/2fa", data={"code": "abc"})
    assert bad.status_code == 401
    assert db.query(LoginAttempt).filter_by(reason="wrong_code").count() == 1

    # De code van nu is al verbruikt bij het aanzetten; de volgende valt binnen de speling.
    ok = client.post("/login/2fa", data={"code": totp.current_code(secret, now=time.time() + 30)}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/portal"
    assert client.get("/portal").status_code == 200


def test_used_code_cannot_be_reused(client, db, staff):
    secret, _ = _enable(client, db, "voorzitter@example.org")
    # De code van het aanzetten is al verbruikt.
    login_resp = client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"}, follow_redirects=False)
    assert login_resp.headers["location"] == "/login/2fa"
    used = db.query(User).filter_by(email="voorzitter@example.org").one().totp_last_step
    assert client.post("/login/2fa", data={"code": totp.current_code(secret, now=used * 30)}).status_code == 401


def test_login_with_recovery_code(client, db, staff):
    _, codes = _enable(client, db, "secretaris@example.org")
    client.post("/login", data={"email": "secretaris@example.org", "password": "geheim12345"})
    r = client.post("/login/2fa", data={"code": codes[3]}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/account")
    assert "9" in page.text
    client.post("/logout")
    client.post("/login", data={"email": "secretaris@example.org", "password": "geheim12345"})
    assert client.post("/login/2fa", data={"code": codes[3]}).status_code == 401


def test_too_many_wrong_codes_locks(client, db, staff):
    _enable(client, db, "voorzitter@example.org")
    client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"})
    for _ in range(5):
        client.post("/login/2fa", data={"code": "999999"})
    r = client.post("/login/2fa", data={"code": "999999"})
    assert r.status_code == 429
    # Ook opnieuw het wachtwoord invullen helpt niet.
    again = client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"})
    assert again.status_code == 429


def test_2fa_page_without_password_step(client, staff):
    assert client.get("/login/2fa", follow_redirects=False).headers["location"] == "/login"
    assert client.post("/login/2fa", data={"code": "123456"}, follow_redirects=False).headers["location"] == "/login"


def test_disable_needs_password(client, db, staff):
    secret, codes = _enable(client, db, "voorzitter@example.org")
    client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"})
    client.post("/login/2fa", data={"code": codes[0]})
    assert client.post("/account/2fa/disable", data={"password": "fout"}).status_code == 422
    assert client.post("/account/2fa/disable", data={"password": "geheim12345"}).status_code == 200
    client.post("/logout")
    r = client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"}, follow_redirects=False)
    assert r.headers["location"] == "/portal"


def test_admin_can_reset_2fa(client, db, staff):
    _enable(client, db, "voorzitter@example.org")
    chair = staff["chair"]
    # Alleen een beheerder.
    client.post("/login", data={"email": "secretaris@example.org", "password": "geheim12345"})
    assert client.post(f"/portal/users/{chair.id}/reset-2fa").status_code == 403
    client.post("/logout")

    login(client, "boekhouder@example.org")
    assert "2FA" in client.get("/portal/users").text
    r = client.post(f"/portal/users/{chair.id}/reset-2fa", follow_redirects=False)
    assert r.status_code == 303
    db.refresh(chair)
    assert not chair.has_2fa and chair.recovery_codes == ""


def _mailed_code() -> str:
    from app import mailer

    body = mailer.outbox[-1].get_content()
    return re.search(r"^(\d{6})$", body, re.M).group(1)


def _enable_email(client, db, email):
    from app import mailer

    login(client, email)
    page = client.post("/account/2fa/email/start")
    assert page.status_code == 200 and mailer.outbox[-1]["To"] == email
    assert client.post("/account/2fa/email", data={"code": "abcdef"}).status_code == 422
    r = client.post("/account/2fa/email", data={"code": _mailed_code()})
    assert r.status_code == 200
    codes = re.findall(r"<li><code>([a-z0-9]{5}-[a-z0-9]{5})</code></li>", r.text)
    assert len(codes) == 10
    client.post("/logout")
    return codes


def _age_email_code(db, email, seconds):
    from datetime import UTC, datetime, timedelta

    user = db.query(User).filter_by(email=email).one()
    db.refresh(user)
    user.email_code_sent_at = datetime.now(UTC) - timedelta(seconds=seconds)
    db.commit()


def test_email_2fa_login(client, db, staff):
    from app import mailer

    _enable_email(client, db, "secretaris@example.org")
    user = db.query(User).filter_by(email="secretaris@example.org").one()
    db.refresh(user)
    assert user.twofa_method == "email"
    _age_email_code(db, "secretaris@example.org", 120)

    sent = len(mailer.outbox)
    r = client.post("/login", data={"email": "secretaris@example.org", "password": "geheim12345"}, follow_redirects=False)
    assert r.headers["location"] == "/login/2fa" and len(mailer.outbox) == sent + 1
    assert "e-mail" in client.get("/login/2fa").text
    code = _mailed_code()
    assert client.post("/login/2fa", data={"code": "000000" if code != "000000" else "111111"}).status_code == 401
    # Meteen opnieuw laten sturen mag niet.
    assert client.post("/login/2fa/resend").status_code == 429
    ok = client.post("/login/2fa", data={"code": code}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/portal"

    # Een gebruikte code werkt niet nog eens.
    client.post("/logout")
    _age_email_code(db, "secretaris@example.org", 120)
    client.post("/login", data={"email": "secretaris@example.org", "password": "geheim12345"})
    assert client.post("/login/2fa", data={"code": code}).status_code == 401


def test_email_code_expires(client, db, staff):
    _enable_email(client, db, "secretaris@example.org")
    _age_email_code(db, "secretaris@example.org", 120)
    client.post("/login", data={"email": "secretaris@example.org", "password": "geheim12345"})
    code = _mailed_code()
    _age_email_code(db, "secretaris@example.org", 11 * 60)
    assert client.post("/login/2fa", data={"code": code}).status_code == 401
    assert client.post("/login/2fa/resend").status_code == 200
    assert client.post("/login/2fa", data={"code": _mailed_code()}, follow_redirects=False).status_code == 303


def test_email_2fa_recovery_and_reset(client, db, staff):
    codes = _enable_email(client, db, "voorzitter@example.org")
    client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"})
    assert client.post("/login/2fa", data={"code": codes[0]}, follow_redirects=False).status_code == 303
    client.post("/logout")
    login(client, "boekhouder@example.org")
    assert "E-mail" in client.get("/portal/users").text
    client.post(f"/portal/users/{staff['chair'].id}/reset-2fa")
    db.refresh(staff["chair"])
    assert not staff["chair"].has_2fa and staff["chair"].email_code_hash == ""
