"""Inloggen, uitloggen en eigen account."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import activity
from ..db import get_db
from ..i18n import available_languages
from ..models import User
from ..security import hash_password, verify_password
from ..web import current_user, render, request_language

router = APIRouter()

# Eenvoudige bescherming tegen wachtwoorden raden: na 5 mislukte pogingen op een account,
# of 20 vanaf één IP-adres (meerdere accounts proberen), 15 minuten wachten.
MAX_ATTEMPTS = 5
MAX_ATTEMPTS_PER_IP = 20
LOCKOUT = timedelta(minutes=15)
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
        return render(
            request, "login.html", request_language(request), status_code=401,
            next=_safe_next(next), error="error.login",
        )
    _failures.pop(key, None)
    activity.record_login(db, key, ip, agent, user=user)
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["lang"] = user.language
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/account")
def account_page(request: Request, user: User = Depends(current_user)):
    return render(request, "account.html", user.language, user=user, message=None, error=None)


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
        return render(request, "account.html", user.language, status_code=422, user=user, message=None, error=error)
    db.commit()
    return render(request, "account.html", user.language, user=user, message="msg.saved", error=None)
