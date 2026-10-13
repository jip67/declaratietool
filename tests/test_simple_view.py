from sqlalchemy import select

from app.models import Claim, Status

from .conftest import login
from .test_claim_admin import make_claim


def enable(db, user):
    user.simple_view = True
    db.commit()


def test_chair_sees_only_own_tasks_as_cards_and_returns_after_approving(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    enable(db, staff["chair"])
    client.post("/logout")
    login(client, "voorzitter@example.org")

    page = client.get("/portal")
    assert "Hallo Vera" in page.text and "Bekijken en goedkeuren" in page.text
    assert "/portal/mail" not in page.text and "/portal/users" not in page.text  # geen instellingen
    assert 'href="/portal/claims/new"' not in page.text

    r = client.post(f"/portal/claims/{claim.id}/action", data={"action": "approve"}, follow_redirects=False)
    assert r.headers["location"] == f"/portal?done={claim.reference}"
    page = client.get(r.headers["location"])
    assert "Gelukt" in page.text and "Er wacht nu niets op jou" in page.text
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    # De volledige lijst blijft bereikbaar.
    assert claim.reference in client.get("/portal?view=all").text


def test_user_switches_simple_view_in_profile(db, client, staff):
    login(client, "secretaris@example.org")
    client.post("/account", data={"name": "Sam Secretaris", "language": "nl", "simple_view": "true"})
    db.expire_all()
    assert staff["secretary"].simple_view
    assert "Hallo Sam" in client.get("/portal").text
    client.post("/account", data={"name": "Sam Secretaris", "language": "nl"})
    db.expire_all()
    assert not staff["secretary"].simple_view


def test_admin_sets_simple_view_for_someone(db, client, staff):
    login(client, "boekhouder@example.org")
    chair = staff["chair"]
    client.post(
        f"/portal/users/{chair.id}",
        data={"name": chair.name, "email": chair.email, "language": "nl", "roles": ["chair"],
              "active": "true", "simple_view": "true"},
    )
    db.expire_all()
    assert chair.simple_view
    # Meekijken toont dan ook de eenvoudige weergave.
    client.post(f"/portal/users/{chair.id}/view-as")
    assert "Hallo Vera" in client.get("/portal").text
