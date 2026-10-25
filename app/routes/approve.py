"""Goedkeuren via de link in de mail, zonder inloggen (zie approval_links.py).

GET toont de declaratie met een knop; alleen POST (de knop) keurt goed.
"""

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import approval_links, storage, workflow
from ..db import get_db
from ..models import ApprovalLink, Attachment, utcnow
from ..web import file_response, render, request_language

log = logging.getLogger(__name__)

router = APIRouter()


def _link(db: Session, token: str) -> ApprovalLink:
    link = approval_links.find(db, token)
    if link is None:
        raise HTTPException(status_code=404)
    return link


def _page(request: Request, link: ApprovalLink, token: str, status_code: int = 200, **context):
    lang = request_language(request, link.user.language if link.user else None)
    return render(
        request, "public/approve.html", lang, status_code=status_code,
        claim=link.claim, token=token, problem=approval_links.problem(link),
        fingerprint=approval_links.fingerprint(link.claim), **context,
    )


@router.get("/a/{token}")
def approve_page(token: str, request: Request, db: Session = Depends(get_db)):
    link = _link(db, token)
    return _page(request, link, token, done=request.query_params.get("done") == "1")


@router.post("/a/{token}")
def approve_submit(token: str, request: Request, fingerprint: str = Form(""), db: Session = Depends(get_db)):
    link = _link(db, token)
    if approval_links.problem(link):
        return RedirectResponse(f"/a/{token}", status_code=303)
    claim = link.claim
    if fingerprint != approval_links.fingerprint(claim):
        # De gegevens zijn gewijzigd sinds de pagina werd geopend: eerst opnieuw laten bekijken.
        return _page(request, link, token, status_code=409, changed=True)
    ip = request.client.host if request.client else ""
    try:
        workflow.approve(db, claim, link.user, via_link=True)
    except workflow.WorkflowError:
        db.rollback()
        return RedirectResponse(f"/a/{token}", status_code=303)
    link.used_at = utcnow()
    link.used_ip = ip[:64]
    db.commit()
    log.info("Declaratie %s goedgekeurd via link door gebruiker %s vanaf %s", claim.reference, link.user_id, ip)
    return RedirectResponse(f"/a/{token}?done=1", status_code=303)


@router.get("/a/{token}/files/{attachment_id}")
def approve_file(token: str, attachment_id: int, db: Session = Depends(get_db)):
    link = _link(db, token)
    att = db.get(Attachment, attachment_id)
    if approval_links.problem(link) or att is None or att.claim_id != link.claim_id:
        raise HTTPException(status_code=404)
    return file_response(storage.absolute(att.stored_path), att.content_type, att.original_filename)
