"""Een factuur die de voorzitter al tekende (bijvoorbeeld per mail binnengekomen) slaat de paraafstap over."""

from sqlalchemy import select

from app import intake, mailer
from app.models import Claim, Event, Status

from .conftest import jpeg_bytes, login, pdf_bytes
from .test_workflow import IBAN, make_mail, sent_to

DETAILS = {"iban": IBAN, "account_holder": "P. Jansen", "description": "Zaalhuur", "amount": "80,00"}


def _submitted_claim(db, client):
    intake.process_message(db, make_mail([("factuur.pdf", "application/pdf", pdf_bytes())]))
    claim = db.scalar(select(Claim))
    client.post(f"/c/{claim.token}", data=DETAILS)
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value
    return claim


def _mark(client, claim, chair_id):
    return client.post(f"/portal/claims/{claim.id}/action",
                       data={"action": "signed_on_paper", "chair_id": str(chair_id)}, follow_redirects=False)


def test_treasurer_marks_submitted_claim_as_signed(db, client, staff):
    claim = _submitted_claim(db, client)
    login(client, "boekhouder@example.org")
    page = client.get(f"/portal/claims/{claim.id}").text
    assert "Al getekend door de voorzitter?" in page and "Vera Voorzitter" in page
    mailer.outbox.clear()
    r = _mark(client, claim, staff["chair"].id)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    assert claim.approved_by_id == staff["chair"].id
    assert claim.signed_on_paper_by_id == staff["chair"].id
    assert claim.approval_signature is None
    # Geen extra paraaf: de handtekening staat al op de factuur.
    assert all(att.stamped_path is None for att in claim.attachments)
    # De boekhouder krijgt de taak, de voorzitter niet.
    assert any("taak" in m["Subject"].lower() or claim.reference in m["Subject"] for m in sent_to("boekhouder@example.org"))
    assert not sent_to("voorzitter@example.org")
    actions = [e.action for e in db.scalars(select(Event).where(Event.claim_id == claim.id))]
    assert "signed_on_paper" in actions and actions[-1] == "approved"
    page = client.get(f"/portal/claims/{claim.id}").text
    assert "Al getekend door Vera Voorzitter (buiten de tool)" in page
    assert "al getekend, buiten de tool" in page


def test_secretary_and_chair_cannot_mark(db, client, staff):
    claim = _submitted_claim(db, client)
    for email in ("secretaris@example.org", "voorzitter@example.org"):
        login(client, email)
        assert "Al getekend door de voorzitter?" not in client.get(f"/portal/claims/{claim.id}").text
        r = _mark(client, claim, staff["chair"].id)
        assert "error=not_allowed" in r.headers["location"]
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value


def test_signer_must_be_a_chair(db, client, staff):
    claim = _submitted_claim(db, client)
    login(client, "boekhouder@example.org")
    r = _mark(client, claim, staff["secretary"].id)
    assert "error=chair_required" in r.headers["location"]
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value and claim.signed_on_paper_by_id is None


def test_mark_before_details_approves_when_details_arrive(db, client, staff):
    intake.process_message(db, make_mail([("factuur.jpg", "image/jpeg", jpeg_bytes())]))
    claim = db.scalar(select(Claim))
    login(client, "boekhouder@example.org")
    _mark(client, claim, staff["chair"].id)
    db.expire_all()
    assert claim.status == Status.RECEIVED.value
    assert "Zodra de gegevens zijn ingevuld" in client.get(f"/portal/claims/{claim.id}").text
    mailer.outbox.clear()
    client.post(f"/c/{claim.token}", data=DETAILS)
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    assert claim.approved_by_id == staff["chair"].id
    assert not sent_to("voorzitter@example.org")
    assert sent_to("boekhouder@example.org")


def test_cancel_mark_while_waiting_for_details(db, client, staff):
    intake.process_message(db, make_mail([("factuur.jpg", "image/jpeg", jpeg_bytes())]))
    claim = db.scalar(select(Claim))
    login(client, "boekhouder@example.org")
    _mark(client, claim, staff["chair"].id)
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "signed_on_paper_cancel"})
    db.expire_all()
    assert claim.signed_on_paper_by_id is None
    client.post(f"/c/{claim.token}", data=DETAILS)
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value
    assert sent_to("voorzitter@example.org")


def test_new_claim_already_signed_goes_to_treasurer(db, client, staff):
    login(client, "boekhouder@example.org")
    assert "Al getekend door Vera Voorzitter" in client.get("/portal/claims/new").text
    mailer.outbox.clear()
    r = client.post("/portal/claims/new", data={"email": "piet@example.org", "name": "Piet", **DETAILS,
                                                "signed_by": str(staff["chair"].id)},
                    files=[("files", ("factuur.pdf", pdf_bytes(), "application/pdf"))], follow_redirects=False)
    assert r.status_code == 303
    claim = db.scalar(select(Claim))
    assert claim.status == Status.APPROVED.value
    assert claim.approved_by_id == staff["chair"].id
    assert not sent_to("voorzitter@example.org")


def test_new_claim_with_invalid_signer_is_refused(db, client, staff):
    login(client, "boekhouder@example.org")
    r = client.post("/portal/claims/new", data={"email": "piet@example.org", **DETAILS,
                                                "signed_by": str(staff["secretary"].id)},
                    files=[("files", ("factuur.pdf", pdf_bytes(), "application/pdf"))])
    assert r.status_code == 422
    assert db.scalar(select(Claim)) is None


def test_undo_returns_to_chair_and_forgets_mark(db, client, staff):
    claim = _submitted_claim(db, client)
    login(client, "boekhouder@example.org")
    _mark(client, claim, staff["chair"].id)
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "undo"})
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value
    assert claim.signed_on_paper_by_id is None and claim.approved_by_id is None


def test_replacing_attachment_adds_no_stamp(db, client, staff):
    claim = _submitted_claim(db, client)
    login(client, "boekhouder@example.org")
    _mark(client, claim, staff["chair"].id)
    att = claim.attachments[0]
    client.post(f"/portal/claims/{claim.id}/attachments/{att.id}/replace",
                files={"file": ("getekend.pdf", pdf_bytes(), "application/pdf")})
    db.expire_all()
    assert claim.attachments[0].original_filename == "getekend.pdf"
    assert claim.attachments[0].stamped_path is None
