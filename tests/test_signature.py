import io
import re

import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select

from app import mailer, storage
from app.models import Attachment, Claim, Status
from app.stamping import SignatureError, normalize_signature, stamp_file, stamp_lines
from app.workflow import WorkflowError, parse_signature

from .conftest import SIGNATURE, jpeg_bytes, login, pdf_bytes, signature_png
from .test_claim_admin import make_claim

ACTION = "/portal/claims/{}/action"


def pdf_has_image(path) -> bool:
    page = PdfReader(str(path)).pages[0]
    xobjects = page["/Resources"].get("/XObject", {})
    return any(obj.get_object().get("/Subtype") == "/Image" or "/XObject" in obj.get_object().get("/Resources", {})
               for obj in xobjects.values())


def png_data(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_normalize_crops_and_colours_signature():
    out = Image.open(io.BytesIO(normalize_signature(signature_png())))
    assert out.mode == "RGBA"
    assert out.width < 400 and out.height < 160  # bijgesneden tot de lijnen
    assert out.getchannel("A").getextrema() == (0, 255)


def test_normalize_accepts_dark_lines_on_white():
    img = Image.new("RGB", (300, 120), "white")
    from PIL import ImageDraw

    ImageDraw.Draw(img).line([(20, 100), (150, 20), (280, 100)], fill="black", width=5)
    assert normalize_signature(png_data(img))


@pytest.mark.parametrize("data", [
    b"",
    b"geen afbeelding",
    png_data(Image.new("RGBA", (400, 160), (0, 0, 0, 0))),  # leeg tekenvlak
    png_data(Image.new("RGB", (400, 160), "white")),
])
def test_normalize_rejects_empty_or_invalid(data):
    with pytest.raises(SignatureError):
        normalize_signature(data)


def test_parse_signature_requires_png_data_url():
    assert parse_signature(SIGNATURE)
    for value in ("", "data:image/jpeg;base64,AAAA", "data:image/png;base64,!!!", "https://example.org/x.png"):
        with pytest.raises(WorkflowError):
            parse_signature(value)


@pytest.mark.parametrize("content_type,data", [("application/pdf", pdf_bytes()), ("image/jpeg", jpeg_bytes())])
def test_stamp_with_signature(tmp_path, content_type, data):
    from datetime import datetime

    source = tmp_path / ("bon.pdf" if content_type == "application/pdf" else "bon.jpg")
    source.write_bytes(data)
    lines = stamp_lines("GOEDGEKEURD", "Vera Voorzitter", datetime(2026, 11, 1, 18, 0), "D2026-001")
    target = stamp_file(source, content_type, lines, normalize_signature(signature_png()))
    reader = PdfReader(str(target))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text() or ""
    if content_type == "application/pdf":
        assert "Vera Voorzitter" in text and "GOEDGEKEURD" not in text
        assert pdf_has_image(target)


def test_portal_approve_needs_signature(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    login(client, "voorzitter@example.org")
    page = client.get(f"/portal/claims/{claim.id}")
    assert "data-signature-pad" in page.text and "/static/js/signature.js" in page.text
    assert "data-saved" not in page.text

    r = client.post(ACTION.format(claim.id), data={"action": "approve"}, follow_redirects=False)
    assert "error=signature_required" in r.headers["location"]
    assert "Zet eerst je paraaf" in client.get(r.headers["location"]).text
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value

    client.post(ACTION.format(claim.id), data={"action": "approve", "signature": SIGNATURE, "remember_signature": "true"})
    db.expire_all()
    assert claim.status == Status.APPROVED.value
    assert claim.approval_signature
    assert staff["chair"].signature == claim.approval_signature
    att = claim.attachments[0]
    assert pdf_has_image(storage.absolute(att.stamped_path))


def test_saved_signature_is_offered_and_can_be_forgotten(db, client, staff):
    make_claim(client)
    make_claim(client)
    first, second = db.scalars(select(Claim).order_by(Claim.id)).all()
    login(client, "voorzitter@example.org")
    client.post(ACTION.format(first.id), data={"action": "approve", "signature": SIGNATURE, "remember_signature": "true"})
    page = client.get(f"/portal/claims/{second.id}")
    assert "data-saved=\"data:image/png;base64," in page.text
    assert re.search(r'name="remember_signature" value="true" checked', page.text)
    # Zonder vinkje wordt de bewaarde paraaf vergeten.
    client.post(ACTION.format(second.id), data={"action": "approve", "signature": SIGNATURE})
    db.expire_all()
    assert second.status == Status.APPROVED.value
    assert staff["chair"].signature is None


def test_undo_forgets_claim_signature(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    login(client, "voorzitter@example.org")
    client.post(ACTION.format(claim.id), data={"action": "approve", "signature": SIGNATURE})
    client.post(ACTION.format(claim.id), data={"action": "undo"})
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value and claim.approval_signature is None


def test_replaced_attachment_gets_drawn_signature(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    login(client, "voorzitter@example.org")
    client.post(ACTION.format(claim.id), data={"action": "approve", "signature": SIGNATURE})
    login(client, "boekhouder@example.org")
    att = db.scalar(select(Attachment))
    client.post(f"/portal/claims/{claim.id}/attachments/{att.id}/replace",
                files={"file": ("nieuw.pdf", pdf_bytes(), "application/pdf")})
    db.expire_all()
    att = db.scalar(select(Attachment))
    assert pdf_has_image(storage.absolute(att.stamped_path))


def test_link_approve_needs_signature(db, client, staff):
    staff["chair"].approve_by_link = True
    db.commit()
    mailer.outbox.clear()
    make_claim(client)
    client.post("/logout")
    claim = db.scalar(select(Claim))
    body = next(m for m in mailer.outbox if m["To"] == "voorzitter@example.org").get_body(("plain",)).get_content()
    path = re.search(r"http://testserver(/a/[\w-]+)", body).group(1)
    page = client.get(path)
    assert "data-signature-pad" in page.text
    fp = re.search(r'name="fingerprint" value="(\w+)"', page.text).group(1)

    r = client.post(path, data={"fingerprint": fp})
    assert r.status_code == 422 and "Zet eerst je paraaf" in r.text
    db.expire_all()
    assert claim.status == Status.SUBMITTED.value

    client.post(path, data={"fingerprint": fp, "signature": SIGNATURE, "remember_signature": "true"})
    db.expire_all()
    assert claim.status == Status.APPROVED.value and claim.approval_signature
    assert staff["chair"].signature


def test_account_signature(db, client, staff):
    login(client, "voorzitter@example.org")
    page = client.get("/account")
    assert "Er is geen paraaf bewaard" in page.text
    assert client.post("/account/signature", data={"signature": ""}).status_code == 422
    r = client.post("/account/signature", data={"signature": SIGNATURE})
    assert "Je paraaf is bewaard" in r.text and 'class="signature-saved"' in r.text
    db.expire_all()
    assert staff["chair"].signature
    r = client.post("/account/signature/delete")
    assert "verwijderd" in r.text
    db.expire_all()
    assert staff["chair"].signature is None

    login(client, "secretaris@example.org")
    assert "data-signature-pad" not in client.get("/account").text
    assert client.post("/account/signature", data={"signature": SIGNATURE}).status_code == 403


def test_after_approval_preview_shows_initialled_version(db, client, staff):
    make_claim(client)
    claim = db.scalar(select(Claim))
    att = claim.attachments[0]
    page = client.get(f"/portal/claims/{claim.id}").text
    assert "met paraaf" not in page and "originele factuur" not in page
    login(client, "voorzitter@example.org")
    client.post(ACTION.format(claim.id), data={"action": "approve", "signature": SIGNATURE})
    login(client, "boekhouder@example.org")
    page = client.get(f"/portal/claims/{claim.id}").text
    stamped = f"/portal/files/{att.id}?stamped=1&amp;v="
    # Het kader en "openen in nieuw venster" tonen de versie met paraaf; het origineel staat er klein onder.
    assert re.search(r'<iframe class="preview pdf" src="' + re.escape(stamped), page)
    assert re.search(r'<a href="' + re.escape(stamped) + r'[^"]*" target="_blank">openen in nieuw venster', page)
    assert re.search(r'<a class="original" href="/portal/files/' + str(att.id) + r'\?v=[^"]*" target="_blank">originele factuur', page)
    assert 'class="badge-paraaf">met paraaf<' in page
