"""Helppagina voor ingelogde gebruikers en medewerkers."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from ..config import get_settings
from ..models import User
from ..web import current_user, render, request_language

router = APIRouter()

HELP_DIR = Path(__file__).parent.parent / "templates" / "help"


@router.get("/help")
def help_page(request: Request, user: User = Depends(current_user)):
    lang = request_language(request, user.language)
    # Helptekst per taal in templates/help/<taal>.html; anders die van de standaardtaal.
    body = lang if (HELP_DIR / f"{lang}.html").exists() else get_settings().default_language
    return render(request, "help.html", lang, user=user, help_body=f"help/{body}.html")
