"""Pagina's voor de indiener (zonder inloggen): bon uploaden en gegevens aanvullen via de persoonlijke link."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage, workflow
from ..config import get_settings
from ..db import get_db
from ..models import Attachment, Claim, Status
from ..security import is_valid_iban, parse_amount
from ..web import file_response, render, request_language

router = APIRouter()

EDITABLE = (Status.RECEIVED, Status.SUBMITTED)


def _claim(db: Session, token: str) -> Claim:
    claim = db.scalar(select(Claim).where(Claim.token == token))
    if claim is None:
        raise HTTPException(status_code=404)
    return claim


def validate_details(iban: str, account_holder: str, description: str, amount: str) -> tuple[dict, int | None]:
    errors = {}
    if not is_valid_iban(iban):
        errors["iban"] = "error.iban"
    if not account_holder.strip():
        errors["account_holder"] = "error.required"
    if not description.strip():
        errors["description"] = "error.required"
    cents = parse_amount(amount)
    if cents is None:
        errors["amount"] = "error.amount"
    return errors, cents


@router.get("/c/{token}")
def claim_page(token: str, request: Request, db: Session = Depends(get_db)):
    claim = _claim(db, token)
    lang = request_language(request, claim.submitter.language)
    amount = f"{claim.amount_cents / 100:.2f}".replace(".", ",") if claim.amount_cents else ""
    form = {
        "iban": claim.iban,
        "account_holder": claim.account_holder,
        "description": claim.description,
        "amount": amount,
    }
    return render(
        request,
        "public/claim.html",
        lang,
        claim=claim,
        form=form,
        errors={},
        editable=claim.status_enum in EDITABLE,
        saved=request.query_params.get("saved") == "1",
    )


@router.post("/c/{token}")
def claim_submit(
    token: str,
    request: Request,
    iban: str = Form(""),
    account_holder: str = Form(""),
    description: str = Form(""),
    amount: str = Form(""),
    remember: bool = Form(False),
    db: Session = Depends(get_db),
):
    claim = _claim(db, token)
    lang = request_language(request, claim.submitter.language)
    if claim.status_enum not in EDITABLE:
        return RedirectResponse(f"/c/{token}", status_code=303)
    errors, cents = validate_details(iban, account_holder, description, amount)
    if errors:
        form = {"iban": iban, "account_holder": account_holder, "description": description, "amount": amount}
        return render(
            request, "public/claim.html", lang, status_code=422,
            claim=claim, form=form, errors=errors, editable=True, saved=False,
        )
    workflow.complete_details(
        db, claim, iban=iban, account_holder=account_holder, description=description,
        amount_cents=cents, remember=remember,
    )
    db.commit()
    return RedirectResponse(f"/c/{token}?saved=1", status_code=303)


@router.get("/c/{token}/files/{attachment_id}")
def claim_file(token: str, attachment_id: int, db: Session = Depends(get_db)):
    claim = _claim(db, token)
    att = db.get(Attachment, attachment_id)
    if att is None or att.claim_id != claim.id:
        raise HTTPException(status_code=404)
    return file_response(storage.absolute(att.stored_path), att.content_type, att.original_filename)


# ---------------------------------------------------------------- uploaden zonder mail

# Eenvoudige rem op misbruik: maximaal zoveel inzendingen per IP-adres per uur.
UPLOADS_PER_HOUR = 10
_uploads: dict[str, list[datetime]] = defaultdict(list)


def _too_many(ip: str) -> bool:
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    _uploads[ip] = [t for t in _uploads[ip] if t > cutoff]
    return len(_uploads[ip]) >= UPLOADS_PER_HOUR


@router.get("/indienen")
def upload_page(request: Request):
    lang = request_language(request)
    return render(request, "public/upload.html", lang, form={}, errors={}, done=False)


@router.post("/indienen")
async def upload_submit(
    request: Request,
    email: str = Form(""),
    name: str = Form(""),
    website: str = Form(""),  # honeypot: echte mensen zien dit veld niet
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    lang = request_language(request)
    form = {"email": email, "name": name}
    if website:
        # Waarschijnlijk een bot: doe alsof het gelukt is.
        return render(request, "public/upload.html", lang, form={}, errors={}, done=True)
    ip = request.client.host if request.client else "?"
    errors = {}
    if _too_many(ip):
        errors["form"] = "error.too_many"
    if "@" not in email or len(email) > 255:
        errors["email"] = "error.email"
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    uploads = []
    for upload in files:
        if not upload.filename:
            continue
        data = await upload.read()
        ctype = storage.guess_type(upload.filename, upload.content_type)
        if ctype is None or len(data) > max_bytes:
            errors["files"] = "error.file_type"
            continue
        uploads.append((upload.filename, ctype, data))
    if not uploads and "files" not in errors:
        errors["files"] = "error.file_required"
    if errors:
        return render(request, "public/upload.html", lang, status_code=422, form=form, errors=errors, done=False)

    _uploads[ip].append(datetime.now(UTC))
    submitter = workflow.get_or_create_submitter(db, email, name, lang)
    claim = workflow.create_claim(db, submitter, uploads, source="upload")
    db.commit()
    # De link gaat alleen per mail naar de indiener, zodat niemand met andermans
    # e-mailadres de onthouden rekeninggegevens kan inzien.
    workflow.notify_received(claim)
    return render(request, "public/upload.html", lang, form={}, errors={}, done=True, email=submitter.email)
