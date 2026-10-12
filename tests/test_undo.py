from sqlalchemy import select

from app import storage
from app.models import Claim, Status

from .conftest import login
from .test_claim_admin import make_claim

ACTION = "/portal/claims/{}/action"


def approved_claim(db, client):
    make_claim(client)  # door boekhouder+beheerder aangemaakt, status ingediend
    claim = db.scalar(select(Claim))
    login(client, "voorzitter@example.org")
    client.post(ACTION.format(claim.id), data={"action": "approve"})
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    return claim


def test_chair_undoes_own_approval(db, client, staff):
    claim = approved_claim(db, client)
    stamped = storage.absolute(claim.attachments[0].stamped_path)
    assert stamped.exists()
    page = client.get(f"/portal/claims/{claim.id}")
    assert 'value="undo"' in page.text

    client.post(ACTION.format(claim.id), data={"action": "undo"})
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value
    assert claim.approved_at is None and claim.approved_by_id is None
    assert claim.attachments[0].stamped_path is None and not stamped.exists()
    assert claim.events[-1].action == "undone" and claim.events[-1].note == "approved"
    assert "Stap ongedaan gemaakt" in client.get(f"/portal/claims/{claim.id}").text

    # Opnieuw goedkeuren werkt gewoon.
    client.post(ACTION.format(claim.id), data={"action": "approve"})
    db.expire_all()
    assert claim.status == Status.APPROVED.value and claim.attachments[0].stamped_path


def test_other_role_cannot_undo(db, client, staff):
    claim = approved_claim(db, client)
    login(client, "secretaris@example.org")
    assert 'value="undo"' not in client.get(f"/portal/claims/{claim.id}").text
    client.post(ACTION.format(claim.id), data={"action": "undo"})
    db.expire_all()
    assert claim.status == Status.APPROVED.value


def test_admin_can_undo_any_step(db, client, staff):
    claim = approved_claim(db, client)
    login(client, "boekhouder@example.org")  # boekhouder + beheerder
    client.post(ACTION.format(claim.id), data={"action": "prepare"})
    login(client, "secretaris@example.org")
    client.post(ACTION.format(claim.id), data={"action": "pay"})
    db.expire_all()
    assert claim.status == Status.PAID.value

    login(client, "boekhouder@example.org")
    for expected in (Status.PAYMENT_PREPARED, Status.APPROVED, Status.SUBMITTED):
        client.post(ACTION.format(claim.id), data={"action": "undo"})
        db.expire_all()
        assert claim.status == expected.value
    # Niets meer om terug te draaien.
    r = client.post(ACTION.format(claim.id), data={"action": "undo"}, follow_redirects=False)
    assert "error=wrong_status" in r.headers["location"]


def test_undo_rejection_restores_previous_status(db, client, staff):
    claim = approved_claim(db, client)
    client.post(ACTION.format(claim.id), data={"action": "reject", "reason": "Dubbel"})
    db.expire_all()
    assert claim.status == Status.REJECTED.value
    client.post(ACTION.format(claim.id), data={"action": "undo"})
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    assert claim.rejection_reason == "" and claim.rejected_by_id is None
