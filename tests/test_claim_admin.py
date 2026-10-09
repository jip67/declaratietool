from pathlib import Path

from sqlalchemy import select

from app import mailer, storage
from app.models import Claim, Comment, Event, IncomingMail, Status
from app.security import hash_password
from app.models import User

from .conftest import login, pdf_bytes

IBAN = "NL91ABNA0417164300"


def make_claim(client, email="boekhouder@example.org"):
    login(client, email)
    client.post(
        "/portal/claims/new",
        data={"email": "indiener@example.org", "name": "Ina Indiener", "iban": IBAN,
              "account_holder": "I. Indiener", "description": "Koffie", "amount": "8,50"},
        files=[("files", ("bon.pdf", pdf_bytes(), "application/pdf"))],
    )


def test_admin_edits_claim(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    page = client.get(f"/portal/claims/{claim.id}/edit")
    assert page.status_code == 200 and "Koffie" in page.text
    r = client.post(
        f"/portal/claims/{claim.id}/edit",
        data={"name": "Ina", "description": "Thee", "amount": "12,00", "iban": IBAN, "account_holder": "Ina I."},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.refresh(claim)
    assert (claim.description, claim.amount_cents, claim.account_holder) == ("Thee", 1200, "Ina I.")
    assert claim.status == Status.SUBMITTED.value
    assert db.scalar(select(Event).where(Event.action == "edited")) is not None


def test_edit_validates(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    r = client.post(f"/portal/claims/{claim.id}/edit",
                    data={"description": "Thee", "amount": "abc", "iban": "NL00", "account_holder": "x"})
    assert r.status_code == 422
    db.refresh(claim)
    assert claim.description == "Koffie"


def test_only_admin_may_edit_or_delete(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    client.cookies.clear()
    login(client, "voorzitter@example.org")
    assert "/edit" not in client.get(f"/portal/claims/{claim.id}").text
    assert client.get(f"/portal/claims/{claim.id}/edit").status_code == 403
    assert client.post(f"/portal/claims/{claim.id}/edit", data={"description": "x"}).status_code == 403
    assert client.post(f"/portal/claims/{claim.id}/delete", data={"confirm": "yes"}).status_code == 403
    assert db.get(Claim, claim.id) is not None


def test_admin_deletes_claim_and_files(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    claim_id = claim.id
    client.post(f"/portal/claims/{claim_id}/action", data={"action": "approve"})
    db.refresh(claim)
    att = claim.attachments[0]
    original, stamped = storage.absolute(att.stored_path), storage.absolute(att.stamped_path)
    assert original.exists() and stamped.exists()
    db.add(IncomingMail(sender="indiener@example.org", subject="bon", result="created", claim_id=claim_id))
    db.commit()
    client.post(f"/portal/claims/{claim_id}/comments", data={"text": "Even nagaan"})

    # Zonder bevestiging gebeurt er niets.
    r = client.post(f"/portal/claims/{claim_id}/delete", follow_redirects=False)
    assert r.status_code == 303 and "error=delete_confirm" in r.headers["location"]
    db.expire_all()
    assert db.get(Claim, claim_id) is not None

    r = client.post(f"/portal/claims/{claim_id}/delete", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Claim, claim_id) is None
    assert db.scalar(select(Comment)) is None
    assert db.scalar(select(IncomingMail)).claim_id is None
    assert not original.exists() and not stamped.exists()
    assert not (Path(storage.upload_root()) / str(claim_id)).exists()


def test_internal_comments_only_for_staff(db, client, staff):
    db.add(User(email="indiener@example.org", name="Ina", password_hash=hash_password("geheim12345"), roles="member"))
    db.commit()
    make_claim(client, "voorzitter@example.org")
    claim = db.scalar(select(Claim))
    r = client.post(f"/portal/claims/{claim.id}/comments", data={"text": "Geheime notitie"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(f"/portal/claims/{claim.id}").text
    assert "Geheime notitie" in page and "niet zichtbaar voor indiener" in page and "Vera Voorzitter" in page

    # Leeg mag niet.
    r = client.post(f"/portal/claims/{claim.id}/comments", data={"text": "  "}, follow_redirects=False)
    assert "error=comment_required" in r.headers["location"]
    assert len(db.scalars(select(Comment)).all()) == 1

    # De indiener ziet hem niet: niet via de persoonlijke link, niet als gebruiker, niet in mails.
    assert "Geheime notitie" not in client.get(f"/c/{claim.token}").text
    assert all("Geheime notitie" not in str(m) for m in mailer.outbox)
    client.cookies.clear()
    login(client, "indiener@example.org")
    page = client.get(f"/portal/claims/{claim.id}")
    assert page.status_code == 200 and "Geheime notitie" not in page.text
    assert client.post(f"/portal/claims/{claim.id}/comments", data={"text": "x"}).status_code == 403


def test_dashboard_shows_comment_icon_for_staff_only(db, client, staff):
    db.add(User(email="indiener@example.org", name="Ina", password_hash=hash_password("geheim12345"), roles="member"))
    db.commit()
    make_claim(client)
    claim = db.scalar(select(Claim))
    assert "comment-flag" not in client.get("/portal").text
    client.post(f"/portal/claims/{claim.id}/comments", data={"text": "Eerste"})
    client.post(f"/portal/claims/{claim.id}/comments", data={"text": "Bon nagevraagd"})
    page = client.get("/portal").text
    assert "comment-flag" in page and "2 interne opmerking(en)" in page and "Bon nagevraagd" in page
    client.cookies.clear()
    login(client, "indiener@example.org")
    page = client.get("/portal").text
    assert claim.reference in page and "comment-flag" not in page and "Bon nagevraagd" not in page
