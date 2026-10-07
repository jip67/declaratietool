"""Pagina's voor de indiener (zonder inloggen, via de persoonlijke link)."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage, workflow
from ..db import get_db
from ..models import Attachment, Claim, Status
from ..security import is_valid_iban, parse_amount
from ..web import render, request_language

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
    return FileResponse(storage.absolute(att.stored_path), media_type=att.content_type, filename=att.original_filename)
