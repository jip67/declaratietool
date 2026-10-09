from sqlalchemy import select

from app.models import Claim, Submitter, User
from app.security import hash_password, verify_password

from .conftest import login, pdf_bytes

IBAN = "NL91ABNA0417164300"


def add_user(db, email="lid@example.org", roles="member"):
    user = User(email=email, name="Lies Lid", password_hash=hash_password("geheim12345"), roles=roles)
    db.add(user)
    db.commit()
    return user


def test_admin_edits_user(db, client, staff):
    member = add_user(db)
    login(client, "boekhouder@example.org")
    page = client.get(f"/portal/users/{member.id}")
    assert page.status_code == 200 and "lid@example.org" in page.text
    r = client.post(
        f"/portal/users/{member.id}",
        data={"name": "Lies de Lid", "email": "Lies@Example.org", "language": "en",
              "roles": ["member", "chair"], "active": "true", "password": "nieuw-wachtwoord"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.refresh(member)
    assert (member.name, member.email, member.language) == ("Lies de Lid", "lies@example.org", "en")
    assert member.roles == "member,chair" and member.active
    assert verify_password("nieuw-wachtwoord", member.password_hash)


def test_edit_refuses_duplicate_email_and_short_password(db, client, staff):
    member = add_user(db)
    login(client, "boekhouder@example.org")
    r = client.post(f"/portal/users/{member.id}", data={"name": "x", "email": "voorzitter@example.org"})
    assert r.status_code == 422
    r = client.post(f"/portal/users/{member.id}", data={"name": "x", "email": "lid@example.org", "password": "kort"})
    assert r.status_code == 422
    db.refresh(member)
    assert member.email == "lid@example.org" and member.name == "Lies Lid"


def test_member_keeps_own_claims_after_email_change(db, client, staff):
    member = add_user(db)
    login(client, "lid@example.org")
    client.post(
        "/portal/claims/new",
        data={"iban": IBAN, "account_holder": "L. Lid", "description": "Koffie", "amount": "8,50"},
        files=[("files", ("bon.pdf", pdf_bytes(), "application/pdf"))],
    )
    claim = db.scalar(select(Claim))
    client.get("/logout")
    login(client, "boekhouder@example.org")
    client.post(f"/portal/users/{member.id}", data={"name": "Lies Lid", "email": "nieuw@example.org", "roles": ["member"], "active": "true"})
    assert db.scalar(select(Submitter).where(Submitter.email == "nieuw@example.org")) is not None
    client.cookies.clear()
    login(client, "nieuw@example.org")
    assert claim.reference in client.get("/portal").text


def test_admin_cannot_lock_out_or_delete_self(db, client, staff):
    me = staff["treasurer"]
    login(client, "boekhouder@example.org")
    client.post(f"/portal/users/{me.id}", data={"name": me.name, "email": me.email, "roles": []})
    db.refresh(me)
    assert me.active and "admin" in me.roles
    r = client.post(f"/portal/users/{me.id}/delete")
    assert r.status_code == 422
    assert db.get(User, me.id) is not None


def test_delete_user_without_history(db, client, staff):
    member_id = add_user(db).id
    login(client, "boekhouder@example.org")
    r = client.post(f"/portal/users/{member_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(User, member_id) is None


def test_delete_user_with_history_anonymises(db, client, staff):
    chair = staff["chair"]
    login(client, "boekhouder@example.org")
    client.post(
        "/portal/claims/new",
        data={"email": "piet@example.org", "iban": IBAN, "account_holder": "P. Jansen", "description": "Koffie", "amount": "8,50"},
        files=[("files", ("bon.pdf", pdf_bytes(), "application/pdf"))],
    )
    claim = db.scalar(select(Claim))
    client.cookies.clear()
    login(client, "voorzitter@example.org")
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "approve"})
    client.cookies.clear()
    login(client, "boekhouder@example.org")
    r = client.post(f"/portal/users/{chair.id}/delete", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    gone = db.get(User, chair.id)
    assert gone is not None and not gone.active and gone.roles == ""
    assert "voorzitter@example.org" not in gone.email
    assert db.get(Claim, claim.id).approved_by_id == chair.id
    assert "voorzitter@example.org" not in client.get("/portal/users").text
    # Inloggen met het oude adres lukt niet meer.
    client.cookies.clear()
    r = client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"}, follow_redirects=False)
    assert r.status_code != 303


def test_only_admin_can_edit_or_delete(db, client, staff):
    member = add_user(db)
    login(client, "voorzitter@example.org")
    assert client.get(f"/portal/users/{member.id}").status_code == 403
    assert client.post(f"/portal/users/{member.id}/delete").status_code == 403
    assert client.get("/portal/users/9999").status_code == 403


def test_settings_menu_per_role(db, client, staff):
    add_user(db)
    login(client, "lid@example.org")
    page = client.get("/portal").text
    assert "Instellingen" not in page and "/portal/users" not in page
    assert client.get("/portal/users").status_code == 403
    client.post("/logout")

    login(client, "voorzitter@example.org")
    page = client.get("/portal").text
    assert "Instellingen" in page
    assert "/portal/users" in page and "/portal/log" in page
    assert "/portal/mail" not in page and "/portal/update" not in page
    client.post("/logout")

    login(client, "boekhouder@example.org")
    page = client.get("/portal").text
    for link in ("/portal/users", "/portal/log", "/portal/mail", "/portal/update"):
        assert link in page


def test_staff_sees_users_read_only(db, client, staff):
    member = add_user(db)
    login(client, "voorzitter@example.org")
    page = client.get("/portal/users")
    assert page.status_code == 200
    assert "Lies Lid" in page.text
    assert f"/portal/users/{member.id}" not in page.text
    assert 'action="/portal/users"' not in page.text
    assert client.get(f"/portal/users/{member.id}").status_code == 403
    assert client.post(f"/portal/users/{member.id}", data={"name": "Gehackt"}).status_code == 403
    assert client.post(f"/portal/users/{member.id}/delete").status_code == 403
    r = client.post("/portal/users", data={"email": "x@example.org", "name": "X", "password": "geheim12345"})
    assert r.status_code == 403
    db.refresh(member)
    assert member.name == "Lies Lid"
