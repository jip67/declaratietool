"""Gedeelde hulpmiddelen voor de webpagina's."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .i18n import available_languages, pick_language, translator
from .models import ROLE_FOR_STATUS, Role, Status, User
from .security import format_iban
from .workflow import local_time

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["localtime"] = local_time
templates.env.filters["iban"] = format_iban


class LoginRequired(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.active:
        raise LoginRequired()
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.has_role(Role.ADMIN):
        raise HTTPException(status_code=403)
    return user


def request_language(request: Request, preferred: str | None = None) -> str:
    return pick_language(
        request.query_params.get("lang"),
        preferred,
        request.session.get("lang"),
        accept_language=request.headers.get("accept-language"),
    )


def render(request: Request, name: str, lang: str, status_code: int = 200, **context):
    settings = get_settings()
    context.update(
        t=translator(lang),
        lang=lang,
        languages=available_languages(),
        settings=settings,
        Status=Status,
        Role=Role,
        ROLE_FOR_STATUS=ROLE_FOR_STATUS,
    )
    return templates.TemplateResponse(request, name, context, status_code=status_code)
