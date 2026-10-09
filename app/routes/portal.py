"""Portaal voor voorzitter, boekhouder, secretaris en beheerder."""

import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import mailconfig, storage, updates, workflow
from ..config import get_settings
from ..db import get_db
from ..i18n import available_languages
from ..models import (
    OPEN_STATUSES, ROLE_FOR_STATUS, Attachment, Claim, Event, IncomingMail, LoginAttempt, Role, Status, Submitter, User,
)
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


DELETED_DOMAIN = "@invalid"


def list_users(db: Session) -> list[User]:
    """Alle gebruikers, zonder de verwijderde (geanonimiseerde) accounts."""
    return db.scalars(select(User).where(User.email.not_like(f"%{DELETED_DOMAIN}")).order_by(User.name)).all()


@router.get("/users")
def users_page(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = list_users(db)
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
        users = list_users(db)
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


def _target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    return target


def _render_edit(request: Request, db: Session, user: User, target: User, error: str | None = None, status_code: int = 200):
    return render(
        request, "portal/user_edit.html", user.language, status_code=status_code,
        user=user, target=target, error=error, has_history=has_history(db, target),
    )


def has_history(db: Session, target: User) -> bool:
    """Komt deze gebruiker voor in een declaratie of het logboek? Dan niet echt verwijderen."""
    fields = (Claim.created_by_id, Claim.approved_by_id, Claim.prepared_by_id, Claim.paid_by_id, Claim.rejected_by_id)
    if db.scalar(select(Claim.id).where(or_(*(f == target.id for f in fields))).limit(1)):
        return True
    return db.scalar(select(Event.id).where(Event.user_id == target.id).limit(1)) is not None


@router.get("/users/{user_id}")
def edit_user_page(user_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _render_edit(request, db, user, _target(db, user_id))


@router.post("/users/{user_id}")
def update_user(
    user_id: int,
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    language: str = Form(""),
    roles: list[str] = Form(default=[]),
    active: bool = Form(False),
    password: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = _target(db, user_id)
    email = email.strip().lower()
    error = None
    if email and "@" not in email:
        error = "error.email"
    elif email and email != target.email and db.scalar(select(User).where(User.email == email)):
        error = "error.user_exists"
    elif password and len(password) < 10:
        error = "error.password_short"
    if error:
        return _render_edit(request, db, user, target, error=error, status_code=422)

    new_roles = [r for r in roles if r in {x.value for x in Role}]
    # Voorkom dat je jezelf buitensluit; zo blijft er ook altijd een beheerder over.
    if target.id == user.id:
        active = True
        if Role.ADMIN.value not in new_roles:
            new_roles.append(Role.ADMIN.value)
    target.roles = ",".join(new_roles)
    target.active = active
    if name.strip():
        target.name = name.strip()
    if language in available_languages():
        target.language = language
    if email and email != target.email:
        # Een gebruiker ziet zijn declaraties via het e-mailadres van de indiener; verhuis dat mee.
        submitter = db.scalar(select(Submitter).where(Submitter.email == target.email))
        if submitter and not db.scalar(select(Submitter).where(Submitter.email == email)):
            submitter.email = email
        target.email = email
    if password:
        target.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse("/portal/users", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = _target(db, user_id)
    if target.id == user.id:
        return _render_edit(request, db, user, target, error="error.delete_self", status_code=422)
    if has_history(db, target):
        # Bewaar het logboek: maak het account onbruikbaar en anoniem in plaats van het te wissen.
        target.name = f"Verwijderde gebruiker {target.id}"
        target.email = f"verwijderd-{target.id}{DELETED_DOMAIN}"
        target.password_hash = hash_password(secrets.token_urlsafe(32))
        target.roles = ""
        target.active = False
    else:
        db.delete(target)
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


# ---------------------------------------------------------------- mailinstellingen


MAIL_ACTIONS = {"save", "test_smtp", "test_imap", "reset"}


def _mail_form(form: dict) -> tuple[mailconfig.MailConfig, dict[str, str]]:
    """Formulier -> MailConfig, plus fouten per veld."""
    config = mailconfig.MailConfig()
    errors = {}
    for name in mailconfig.TEXT_FIELDS + mailconfig.SECRET_FIELDS:
        value = str(form.get(name, ""))
        setattr(config, name, value if name in mailconfig.SECRET_FIELDS else value.strip())
    for name in mailconfig.INT_FIELDS:
        try:
            value = int(str(form.get(name, "")).strip())
            if not 1 <= value <= 65535:
                raise ValueError
            setattr(config, name, value)
        except ValueError:
            errors[name] = "error.port"
    for name in mailconfig.BOOL_FIELDS:
        setattr(config, name, name in form)
    config.imap_folder = config.imap_folder or "INBOX"
    if config.mail_from and "@" not in config.mail_from:
        errors["mail_from"] = "error.email"
    return config, errors


def _render_mail(request: Request, db: Session, user: User, form: mailconfig.MailConfig | None = None,
                 errors: dict | None = None, message: tuple[str, str, str] | None = None, status_code: int = 200):
    current = mailconfig.load(db)
    return render(
        request, "portal/mail.html", user.language, status_code=status_code,
        user=user, form=form or current, current=current, errors=errors or {}, message=message,
    )


@router.get("/mail")
def mail_page(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    saved = request.query_params.get("saved")
    message = ("success", "mail.saved", "") if saved == "1" else ("success", "mail.reset_done", "") if saved == "reset" else None
    return _render_mail(request, db, user, message=message)


@router.post("/mail")
async def mail_save(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    form = await request.form()
    action = form.get("action", "save")
    if action not in MAIL_ACTIONS:
        raise HTTPException(status_code=400)
    if action == "reset":
        mailconfig.reset(db)
        db.commit()
        return RedirectResponse("/portal/mail?saved=reset", status_code=303)

    config, errors = _mail_form(form)
    if errors:
        return _render_mail(request, db, user, form=config, errors=errors, status_code=422)
    if action == "save":
        mailconfig.save(db, config, keep_passwords="clear_passwords" not in form)
        db.commit()
        return RedirectResponse("/portal/mail?saved=1", status_code=303)

    # Testen met wat in het formulier staat; een leeg wachtwoordveld betekent "het opgeslagen wachtwoord".
    current = mailconfig.load(db)
    for name in mailconfig.SECRET_FIELDS:
        if not getattr(config, name):
            setattr(config, name, getattr(current, name))
    kind = "smtp" if action == "test_smtp" else "imap"
    ok, detail = mailconfig.check_smtp(config) if kind == "smtp" else mailconfig.check_imap(config)
    if ok:
        message = ("success", f"mail.test_{kind}_ok", detail)
    elif detail == "no_host":
        message = ("error", f"mail.test_{kind}_no_host", "")
    else:
        message = ("error", f"mail.test_{kind}_failed", detail)
    # Ingevulde wachtwoorden niet terug in de pagina zetten.
    for name in mailconfig.SECRET_FIELDS:
        setattr(config, name, "")
    return _render_mail(request, db, user, form=config, message=message)


# ---------------------------------------------------------------- logboek

LOG_TABS = ("logins", "failed", "mails")
LOG_PAGE_SIZE = 50


@router.get("/log")
def log_page(
    request: Request,
    tab: str = "logins",
    q: str = "",
    page: int = 1,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if tab not in LOG_TABS:
        tab = "logins"
    q = q.strip()
    page = max(page, 1)
    if tab == "mails":
        query = select(IncomingMail)
        if q:
            like = f"%{q}%"
            query = query.where(or_(
                IncomingMail.sender.ilike(like), IncomingMail.subject.ilike(like), IncomingMail.result.ilike(like),
            ))
        order = IncomingMail.at.desc()
    else:
        query = select(LoginAttempt).where(LoginAttempt.success.is_(tab == "logins"))
        if q:
            like = f"%{q}%"
            query = query.where(or_(LoginAttempt.email.ilike(like), LoginAttempt.ip.ilike(like)))
        order = LoginAttempt.at.desc()
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(order).offset((page - 1) * LOG_PAGE_SIZE).limit(LOG_PAGE_SIZE)).all()
    return render(
        request, "portal/log.html", user.language,
        user=user, tab=tab, tabs=LOG_TABS, q=q, page=page, rows=rows, total=total,
        pages=max(1, -(-total // LOG_PAGE_SIZE)), retention_days=get_settings().log_retention_days,
    )
