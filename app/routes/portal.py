"""Portaal voor voorzitter, boekhouder, secretaris en beheerder."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage, updates, workflow
from ..config import get_settings
from ..db import get_db
from ..i18n import available_languages
from ..models import OPEN_STATUSES, ROLE_FOR_STATUS, Attachment, Claim, Role, Status, Submitter, User
from ..security import hash_password
from ..web import current_user, file_response, render, require_admin
from .public import validate_details

router = APIRouter(prefix="/portal")


def can_see(claim: Claim, user: User) -> bool:
    """Medewerkers zien alles; een gebruiker alleen zijn eigen declaraties."""
    return user.is_staff or claim.submitter.email == user.email


def _claim(db: Session, claim_id: int, user: User) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None or not can_see(claim, user):
        raise HTTPException(status_code=404)
    return claim


def is_my_task(claim: Claim, user: User) -> bool:
    role = ROLE_FOR_STATUS.get(claim.status_enum)
    return role is not None and user.has_role(role)


@router.get("")
def dashboard(request: Request, view: str = "open", user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Claim).order_by(Claim.created_at.desc())
    if not user.is_staff:
        claims = db.scalars(query.join(Claim.submitter).where(Submitter.email == user.email).limit(500)).all()
        return render(
            request, "portal/dashboard.html", user.language,
            user=user, claims=claims, view="all", my_count=0, is_my_task=is_my_task,
        )
    if view == "open":
        query = query.where(Claim.status.in_([s.value for s in OPEN_STATUSES]))
    elif view in {s.value for s in Status}:
        query = query.where(Claim.status == view)
    claims = db.scalars(query.limit(500)).all()
    if view == "mine":
        claims = [c for c in claims if is_my_task(c, user)]
    my_count = sum(1 for c in db.scalars(select(Claim).where(Claim.status.in_([s.value for s in ROLE_FOR_STATUS]))) if is_my_task(c, user))
    return render(
        request, "portal/dashboard.html", user.language,
        user=user, claims=claims, view=view, my_count=my_count, is_my_task=is_my_task,
    )


@router.get("/claims/new")
def new_claim_page(request: Request, user: User = Depends(current_user)):
    return render(request, "portal/new.html", user.language, user=user, form={}, errors={})


@router.post("/claims/new")
async def new_claim(
    request: Request,
    email: str = Form(""),
    name: str = Form(""),
    iban: str = Form(""),
    account_holder: str = Form(""),
    description: str = Form(""),
    amount: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not user.is_staff:
        # Een gebruiker dient altijd voor zichzelf in.
        email, name = user.email, user.name
    form = {"email": email, "name": name, "iban": iban, "account_holder": account_holder,
            "description": description, "amount": amount}
    errors = {}
    if "@" not in email:
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
    # Gegevens zijn optioneel; als ze (deels) zijn ingevuld moeten ze kloppen.
    details_given = any(v.strip() for v in (iban, account_holder, description, amount))
    cents = None
    if details_given:
        detail_errors, cents = validate_details(iban, account_holder, description, amount)
        errors.update(detail_errors)
    if errors:
        return render(request, "portal/new.html", user.language, status_code=422, user=user, form=form, errors=errors)

    submitter = workflow.get_or_create_submitter(db, email, name)
    claim = workflow.create_claim(db, submitter, uploads, source="portal", created_by=user)
    if details_given:
        workflow.complete_details(
            db, claim, iban=iban, account_holder=account_holder, description=description,
            amount_cents=cents, remember=True, user=user,
        )
    db.commit()
    if not details_given:
        workflow.notify_received(claim)
    return RedirectResponse(f"/portal/claims/{claim.id}", status_code=303)


@router.get("/claims/{claim_id}")
def claim_detail(claim_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    claim = _claim(db, claim_id, user)
    return render(
        request, "portal/claim.html", user.language,
        user=user, claim=claim, my_task=is_my_task(claim, user),
        error=request.query_params.get("error"), link=workflow.claim_link(claim),
    )


ACTIONS = {
    "approve": workflow.approve,
    "prepare": workflow.prepare_payment,
    "pay": workflow.mark_paid,
}


@router.post("/claims/{claim_id}/action")
def claim_action(
    claim_id: int,
    action: str = Form(...),
    reason: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not user.is_staff:
        raise HTTPException(status_code=403)
    claim = _claim(db, claim_id, user)
    try:
        if action == "reject":
            if not reason.strip():
                raise workflow.WorkflowError("reason_required")
            workflow.reject(db, claim, user, reason)
        elif action in ACTIONS:
            ACTIONS[action](db, claim, user)
        else:
            raise HTTPException(status_code=400)
    except workflow.WorkflowError as exc:
        db.rollback()
        return RedirectResponse(f"/portal/claims/{claim_id}?error={exc}", status_code=303)
    db.commit()
    return RedirectResponse(f"/portal/claims/{claim_id}", status_code=303)


@router.get("/files/{attachment_id}")
def portal_file(attachment_id: int, stamped: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    att = db.get(Attachment, attachment_id)
    if att is None or not can_see(att.claim, user):
        raise HTTPException(status_code=404)
    if stamped and att.stamped_path:
        name = att.original_filename.rsplit(".", 1)[0] + "-paraaf.pdf"
        return file_response(storage.absolute(att.stamped_path), "application/pdf", name)
    return file_response(storage.absolute(att.stored_path), att.content_type, att.original_filename)


# ---------------------------------------------------------------- gebruikersbeheer


@router.get("/users")
def users_page(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.name)).all()
    error = request.query_params.get("error")
    return render(
        request, "portal/users.html", user.language,
        user=user, users=users, error=f"error.{error}" if error else None,
    )


@router.post("/users")
def create_user(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    language: str = Form("nl"),
    roles: list[str] = Form(default=[]),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    error = None
    if "@" not in email:
        error = "error.email"
    elif len(password) < 10:
        error = "error.password_short"
    elif db.scalar(select(User).where(User.email == email)):
        error = "error.user_exists"
    if error:
        users = db.scalars(select(User).order_by(User.name)).all()
        return render(request, "portal/users.html", user.language, status_code=422, user=user, users=users, error=error)
    db.add(
        User(
            email=email,
            name=name.strip(),
            password_hash=hash_password(password),
            roles=",".join(r for r in roles if r in {x.value for x in Role}),
            language=language if language in available_languages() else "nl",
        )
    )
    db.commit()
    return RedirectResponse("/portal/users", status_code=303)


@router.post("/users/{user_id}")
def update_user(
    user_id: int,
    roles: list[str] = Form(default=[]),
    active: bool = Form(False),
    password: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    new_roles = [r for r in roles if r in {x.value for x in Role}]
    # Voorkom dat je jezelf buitensluit.
    if target.id == user.id:
        active = True
        if Role.ADMIN.value not in new_roles:
            new_roles.append(Role.ADMIN.value)
    target.roles = ",".join(new_roles)
    target.active = active
    if password:
        if len(password) < 10:
            return RedirectResponse("/portal/users?error=password_short", status_code=303)
        target.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse("/portal/users", status_code=303)


# ---------------------------------------------------------------- bijwerken


UPDATE_ERRORS = {"update.not_configured", "update.busy"}


@router.get("/update")
def update_page(request: Request, user: User = Depends(require_admin)):
    current = updates.status()
    return render(
        request, "portal/update.html", user.language,
        user=user, available=updates.available(), status=current, pending=updates.pending(),
        busy=updates.is_busy(current), update_available=updates.update_available(current),
        running_version=updates.running_version(), log=updates.log_tail(),
        error=request.query_params.get("error") if request.query_params.get("error") in UPDATE_ERRORS else None,
    )


@router.post("/update")
def request_update(action: str = Form(...), user: User = Depends(require_admin)):
    if action not in updates.ACTIONS:
        raise HTTPException(status_code=400)
    if not updates.available():
        return RedirectResponse("/portal/update?error=update.not_configured", status_code=303)
    if updates.is_busy():
        return RedirectResponse("/portal/update?error=update.busy", status_code=303)
    updates.request(action, user.email)
    return RedirectResponse("/portal/update", status_code=303)
