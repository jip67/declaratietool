"""Helppagina voor indieners en medewerkers."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..web import render, request_language

router = APIRouter()

HELP_DIR = Path(__file__).parent.parent / "templates" / "help"


@router.get("/help")
def help_page(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if user is not None and not user.active:
        user = None
    lang = request_language(request, user.language if user else None)
    # Helptekst per taal in templates/help/<taal>.html; anders die van de standaardtaal.
    body = lang if (HELP_DIR / f"{lang}.html").exists() else get_settings().default_language
    return render(request, "help.html", lang, user=user, help_body=f"help/{body}.html")
