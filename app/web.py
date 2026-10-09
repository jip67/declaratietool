"""Gedeelde hulpmiddelen voor de webpagina's."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db, new_session
from .i18n import available_languages, pick_language, translator
from .models import ROLE_FOR_STATUS, Claim, Role, Status, User
from .security import format_iban
from .workflow import local_time

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["localtime"] = local_time
templates.env.filters["iban"] = format_iban

# Bijlagen die een browser zelf kan tonen; HEIC/HEIF lukt alleen in Safari.
PREVIEW_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def preview_kind(content_type: str) -> str | None:
    if content_type == "application/pdf":
        return "pdf"
    if content_type in PREVIEW_IMAGE_TYPES:
        return "image"
    return None


templates.env.filters["preview_kind"] = preview_kind


def file_response(path: Path, media_type: str, filename: str) -> FileResponse:
    """Stuur een bijlage zo dat de browser hem op de pagina kan tonen (inline) in plaats van te downloaden."""
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


class LoginRequired(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.active:
        raise LoginRequired()
    return user


def require_staff(user: User = Depends(current_user)) -> User:
    """Bestuursleden en beheerders; gewone gebruikers (rol Gebruiker) niet."""
    if not user.is_staff:
        raise HTTPException(status_code=403)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.has_role(Role.ADMIN):
        raise HTTPException(status_code=403)
    return user


def request_language(request: Request, preferred: str | None = None) -> str:
    """Kies de taal: expliciete keuze via ?lang=, dan de opgeslagen keuze, dan de standaardtaal.

    De taal van de browser telt bewust niet mee, zodat iedereen standaard
    DEFAULT_LANGUAGE (Nederlands) ziet en zelf kan wisselen.
    """
    chosen = request.query_params.get("lang")
    if chosen in available_languages():
        request.session["lang"] = chosen
        return chosen
    return pick_language(preferred, request.session.get("lang"))


def is_my_task(claim: Claim, user: User) -> bool:
    role = ROLE_FOR_STATUS.get(claim.status_enum)
    return role is not None and user.has_role(role)


def my_task_count(db: Session, user: User) -> int:
    """Aantal declaraties dat op een actie van deze gebruiker wacht (voor het menu)."""
    claims = db.scalars(select(Claim).where(Claim.status.in_([s.value for s in ROLE_FOR_STATUS])))
    return sum(1 for c in claims if is_my_task(c, user))


def render(request: Request, name: str, lang: str, status_code: int = 200, **context):
    settings = get_settings()
    user = context.get("user")
    if user is not None and user.is_staff and "my_count" not in context:
        db = new_session()
        try:
            context["my_count"] = my_task_count(db, user)
        finally:
            db.close()
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
