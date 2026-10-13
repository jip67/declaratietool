from sqlalchemy import select

from app.models import Claim, LoginAttempt, Status

from .conftest import login
from .test_claim_admin import make_claim
from .test_users import add_user


def start(client, user):
    r = client.post(f"/portal/users/{user.id}/view-as", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/portal"


def test_admin_sees_what_chair_sees_but_cannot_approve(db, client, staff):
    make_claim(client)  # boekhouder (beheerder) is ingelogd
    claim = db.scalar(select(Claim))
    assert claim.status == Status.SUBMITTED.value
    start(client, staff["chair"])

    page = client.get("/portal?view=mine")
    assert "Je kijkt mee als Vera Voorzitter" in page.text and claim.reference in page.text
    detail = client.get(f"/portal/claims/{claim.id}")
    assert 'value="approve"' in detail.text  # de knop is te zien, zoals bij de voorzitter

    r = client.post(
        f"/portal/claims/{claim.id}/action", data={"action": "approve"},
        headers={"referer": f"http://testserver/portal/claims/{claim.id}"}, follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == f"/portal/claims/{claim.id}"
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value
    assert "Dat kan niet tijdens meekijken" in client.get(f"/portal/claims/{claim.id}").text


def test_view_as_blocks_all_changes_and_admin_pages(db, client, staff):
    login(client, "boekhouder@example.org")
    start(client, staff["secretary"])
    assert client.get("/portal/mail").status_code == 403  # de secretaris is geen beheerder
    client.post("/account", data={"name": "Gewijzigd", "language": "nl"})
    client.post(f"/portal/users/{staff['chair'].id}/view-as")
    db.expire_all()
    assert staff["secretary"].name == "Sam Secretaris"


def test_stop_returns_to_own_account(db, client, staff):
    login(client, "boekhouder@example.org")
    start(client, staff["chair"])
    r = client.post("/portal/view-as/stop", follow_redirects=False)
    assert r.headers["location"] == f"/portal/users/{staff['chair'].id}"
    page = client.get("/portal")
    assert "Je kijkt mee" not in page.text
    assert client.get("/portal/mail").status_code == 200


def test_view_as_member_shows_only_their_claims(db, client, staff):
    member = add_user(db)
    make_claim(client)
    start(client, member)
    page = client.get("/portal")
    assert "Je kijkt mee als Lies Lid" in page.text
    claim = db.scalar(select(Claim))
    assert claim.reference not in page.text
    assert client.get(f"/portal/claims/{claim.id}").status_code == 404


def test_only_admin_can_view_as_and_it_is_logged(db, client, staff):
    login(client, "voorzitter@example.org")
    r = client.post(f"/portal/users/{staff['secretary'].id}/view-as", follow_redirects=False)
    assert r.status_code == 403
    client.post("/logout")
    login(client, "boekhouder@example.org")
    start(client, staff["chair"])
    row = db.scalar(select(LoginAttempt).where(LoginAttempt.reason == "view_as"))
    assert row.user_id == staff["treasurer"].id and "voorzitter@example.org" in row.user_agent
    client.post("/portal/view-as/stop")
    assert "Meegekeken als Vera Voorzitter" in client.get("/portal/log").text


def test_view_as_ends_when_target_is_deactivated(db, client, staff):
    login(client, "boekhouder@example.org")
    start(client, staff["chair"])
    staff["chair"].active = False
    db.commit()
    page = client.get("/portal")
    assert "Je kijkt mee" not in page.text
    assert client.get("/portal/mail").status_code == 200
