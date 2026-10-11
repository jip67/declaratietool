"""Inloggen, uitloggen en eigen account."""

import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import activity, mailer, notifications, totp
from ..db import get_db
from ..i18n import available_languages, translate
from ..models import User
from ..security import hash_password, verify_password
from ..config import get_settings
from ..web import current_user, render, request_language

router = APIRouter()

# Eenvoudige bescherming tegen wachtwoorden raden: na 5 mislukte pogingen op een account,
# of 20 vanaf één IP-adres (meerdere accounts proberen), 15 minuten wachten.
MAX_ATTEMPTS = 5
MAX_ATTEMPTS_PER_IP = 20
LOCKOUT = timedelta(minutes=15)
# Na het wachtwoord heeft iemand zoveel tijd om de code uit de authenticator-app in te vullen.
PENDING_2FA_SECONDS = 5 * 60
_failures: dict[str, list[datetime]] = defaultdict(list)


def _locked(key: str, limit: int = MAX_ATTEMPTS) -> bool:
    cutoff = datetime.now(UTC) - LOCKOUT
    _failures[key] = [t for t in _failures[key] if t > cutoff]
    return len(_failures[key]) >= limit


def _safe_next(target: str | None) -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/portal"


@router.get("/login")
def login_page(request: Request, next: str = "/portal"):
    return render(request, "login.html", request_language(request), next=_safe_next(next), error=None)


@router.post("/login")
def login(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/portal"),
    db: Session = Depends(get_db),
):
    key = email.strip().lower()
    ip = request.client.host if request.client else "?"
    ip_key = "ip:" + ip
    agent = request.headers.get("user-agent", "")
    if _locked(key) or _locked(ip_key, MAX_ATTEMPTS_PER_IP):
        activity.record_login(db, key, ip, agent, reason="locked")
        return render(
            request, "login.html", request_language(request), status_code=429,
            next=_safe_next(next), error="error.login_locked",
        )
    user = db.scalar(select(User).where(User.email == key))
    if user is None or not user.active or not verify_password(password, user.password_hash):
        if user is None:
            reason = "unknown_user"
        elif not user.active:
            reason = "inactive"
        else:
            reason = "wrong_password"
        activity.record_login(db, key, ip, agent, user=user, reason=reason)
        _failures[key].append(datetime.now(UTC))
        _failures[ip_key].append(datetime.now(UTC))
        # Precies op de grens gaat de blokkering in: dan één melding, niet bij elke volgende poging.
        if len(_failures[key]) == MAX_ATTEMPTS:
            notifications.lockout(db, key, ip, by_ip=False, background=background)
        elif len(_failures[ip_key]) == MAX_ATTEMPTS_PER_IP:
            notifications.lockout(db, key, ip, by_ip=True, background=background)
        return render(
            request, "login.html", request_language(request), status_code=401,
            next=_safe_next(next), error="error.login",
        )
    request.session.clear()
    if user.has_2fa:
        # Wachtwoord klopt; nu nog de code. Mislukte pogingen blijven tellen tot de code ook goed is.
        request.session["pending_2fa"] = {"user_id": user.id, "next": _safe_next(next), "at": int(time.time())}
        request.session["lang"] = user.language
        # Een code van minder dan een minuut oud blijft gewoon geldig; zo kan niemand de mailbox volspammen.
        if user.twofa_method == "email" and totp.can_resend_email_code(user):
            _send_email_code(db, user, background)
        return RedirectResponse("/login/2fa", status_code=303)
    return _finish_login(request, db, user, ip, agent, next, background)


def _send_email_code(db: Session, user: User, background: BackgroundTasks) -> None:
    code = totp.new_email_code(user)
    db.commit()
    lang = user.language
    minutes = int(totp.EMAIL_CODE_VALID.total_seconds() // 60)
    app = get_settings().app_name
    mail = mailer.Mail(
        to=[user.email],
        subject=translate("2fa.mail.subject", lang, app=app),
        body=translate("2fa.mail.body", lang, name=user.name, app=app, code=code, minutes=minutes),
    )
    background.add_task(mailer.send, mail)


def _finish_login(request: Request, db: Session, user: User, ip: str, agent: str, next: str, background: BackgroundTasks):
    _failures.pop(user.email, None)
    activity.record_login(db, user.email, ip, agent, user=user)
    notifications.login(db, user, ip, agent, background)
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["lang"] = user.language
    return RedirectResponse(_safe_next(next), status_code=303)


def _pending_user(request: Request, db: Session) -> User | None:
    pending = request.session.get("pending_2fa")
    if not isinstance(pending, dict) or time.time() - pending.get("at", 0) > PENDING_2FA_SECONDS:
        return None
    user = db.get(User, pending.get("user_id"))
    if user is None or not user.active or not user.has_2fa:
        return None
    return user


@router.get("/login/2fa")
def login_2fa_page(request: Request, db: Session = Depends(get_db)):
    user = _pending_user(request, db)
    if user is None:
        request.session.pop("pending_2fa", None)
        return RedirectResponse("/login", status_code=303)
    return _render_2fa(request, user, request_language(request))


def _render_2fa(request: Request, user: User, lang: str, error: str | None = None, message: str | None = None, status_code: int = 200):
    return render(
        request, "login_2fa.html", lang, status_code=status_code,
        method=user.twofa_method, error=error, message=message,
    )


@router.post("/login/2fa/resend")
def login_2fa_resend(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    user = _pending_user(request, db)
    if user is None:
        request.session.pop("pending_2fa", None)
        return RedirectResponse("/login", status_code=303)
    lang = request_language(request, user.language)
    if user.twofa_method != "email" or not totp.can_resend_email_code(user):
        return _render_2fa(request, user, lang, error="error.code_resend_wait", status_code=429)
    _send_email_code(db, user, background)
    return _render_2fa(request, user, lang, message="2fa.mail_resent")


@router.post("/login/2fa")
def login_2fa(
    request: Request,
    background: BackgroundTasks,
    code: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _pending_user(request, db)
    if user is None:
        request.session.pop("pending_2fa", None)
        return RedirectResponse("/login", status_code=303)
    next = request.session["pending_2fa"].get("next", "/portal")
    lang = request_language(request, user.language)
    ip = request.client.host if request.client else "?"
    ip_key = "ip:" + ip
    agent = request.headers.get("user-agent", "")
    if _locked(user.email) or _locked(ip_key, MAX_ATTEMPTS_PER_IP):
        activity.record_login(db, user.email, ip, agent, user=user, reason="locked")
        request.session.clear()
        return render(request, "login.html", lang, status_code=429, next=next, error="error.login_locked")

    if user.twofa_method == "app":
        step = totp.verify(user.totp_secret, code, user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            db.commit()
            return _finish_login(request, db, user, ip, agent, next, background)
    elif totp.use_email_code(user, code):
        db.commit()
        return _finish_login(request, db, user, ip, agent, next, background)
    remaining = totp.use_recovery_code(user.recovery_codes, code)
    if remaining is not None:
        user.recovery_codes = remaining
        db.commit()
        return _finish_login(request, db, user, ip, agent, next, background)

    activity.record_login(db, user.email, ip, agent, user=user, reason="wrong_code")
    _failures[user.email].append(datetime.now(UTC))
    _failures[ip_key].append(datetime.now(UTC))
    if len(_failures[user.email]) == MAX_ATTEMPTS:
        notifications.lockout(db, user.email, ip, by_ip=False, background=background)
    elif len(_failures[ip_key]) == MAX_ATTEMPTS_PER_IP:
        notifications.lockout(db, user.email, ip, by_ip=True, background=background)
    return _render_2fa(request, user, lang, error="error.code_wrong", status_code=401)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/account")
def account_page(request: Request, user: User = Depends(current_user)):
    return _render_account(request, user)


@router.post("/account")
def account_update(
    request: Request,
    name: str = Form(...),
    language: str = Form(...),
    current_password: str = Form(""),
    new_password: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    error = None
    user.name = name.strip() or user.name
    if language in available_languages():
        user.language = language
        request.session["lang"] = language
    if new_password:
        if not verify_password(current_password, user.password_hash):
            error = "error.password_wrong"
        elif len(new_password) < 10:
            error = "error.password_short"
        else:
            user.password_hash = hash_password(new_password)
    if error:
        db.rollback()
        return _render_account(request, user, error=error, status_code=422)
    db.commit()
    return _render_account(request, user, message="msg.saved")


# ---------------------------------------------------------------- tweestapsverificatie


def _render_account(request: Request, user: User, message: str | None = None, error: str | None = None, status_code: int = 200):
    return render(
        request, "account.html", user.language, status_code=status_code,
        user=user, message=message, error=error, codes_left=totp.recovery_codes_left(user.recovery_codes),
    )


def _render_setup(request: Request, user: User, secret: str, error: str | None = None, status_code: int = 200):
    uri = totp.provisioning_uri(secret, user.email, get_settings().app_name)
    return render(
        request, "account_2fa.html", user.language, status_code=status_code,
        user=user, qr=totp.qr_svg(uri), secret=totp.format_secret(secret), error=error,
    )


def _render_codes(request: Request, user: User, codes: list[str]):
    return render(request, "account_codes.html", user.language, user=user, codes=codes)


@router.get("/account/2fa")
def setup_2fa_page(request: Request, user: User = Depends(current_user)):
    if user.has_2fa:
        return RedirectResponse("/account", status_code=303)
    # Het geheim wordt pas bij het account opgeslagen als de eerste code klopt.
    secret = request.session.get("totp_setup") or totp.new_secret()
    request.session["totp_setup"] = secret
    return _render_setup(request, user, secret)


@router.post("/account/2fa")
def setup_2fa(
    request: Request,
    code: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.has_2fa:
        return RedirectResponse("/account", status_code=303)
    secret = request.session.get("totp_setup")
    if not secret:
        return RedirectResponse("/account/2fa", status_code=303)
    step = totp.verify(secret, code)
    if step is None:
        return _render_setup(request, user, secret, error="error.code_wrong", status_code=422)
    codes, hashes = totp.new_recovery_codes()
    user.totp_secret = secret
    user.totp_last_step = step
    user.recovery_codes = hashes
    db.commit()
    request.session.pop("totp_setup", None)
    return _render_codes(request, user, codes)


@router.post("/account/2fa/email/start")
def setup_email_2fa_start(
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.has_2fa:
        return RedirectResponse("/account", status_code=303)
    # Eerst een code sturen: zo weten we zeker dat de mail aankomt voordat het aan gaat.
    if totp.can_resend_email_code(user):
        _send_email_code(db, user, background)
    return render(request, "account_2fa_email.html", user.language, user=user, error=None)


@router.post("/account/2fa/email")
def setup_email_2fa(
    request: Request,
    code: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.has_2fa:
        return RedirectResponse("/account", status_code=303)
    if not totp.use_email_code(user, code):
        return render(request, "account_2fa_email.html", user.language, status_code=422, user=user, error="error.code_wrong")
    codes, hashes = totp.new_recovery_codes()
    user.email_2fa = True
    user.recovery_codes = hashes
    db.commit()
    return _render_codes(request, user, codes)


@router.post("/account/2fa/disable")
def disable_2fa(
    request: Request,
    password: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(password, user.password_hash):
        return _render_account(request, user, error="error.password_wrong", status_code=422)
    user.clear_2fa()
    db.commit()
    return _render_account(request, user, message="msg.2fa_disabled")


@router.post("/account/2fa/recovery")
def regenerate_recovery_codes(
    request: Request,
    password: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not user.has_2fa:
        return RedirectResponse("/account", status_code=303)
    if not verify_password(password, user.password_hash):
        return _render_account(request, user, error="error.password_wrong", status_code=422)
    codes, hashes = totp.new_recovery_codes()
    user.recovery_codes = hashes
    db.commit()
    return _render_codes(request, user, codes)
