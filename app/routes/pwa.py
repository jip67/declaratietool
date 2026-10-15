"""Web-app (PWA): manifest, service worker en offline-pagina, zodat de tool op een telefoon als app te installeren is."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from ..config import get_settings
from ..db import get_db
from ..models import User
from sqlalchemy.orm import Session

from ..web import logged_in_user, my_task_count, render, request_language

router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent / "static"
THEME_COLOR = "#4338ca"
BACKGROUND_COLOR = "#f3f5fb"


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    settings = get_settings()
    icons = "/static/icons"
    data = {
        "name": f"{settings.app_name} · {settings.organisation_name}",
        "short_name": settings.app_name,
        "id": "/portal",
        "start_url": "/portal",
        "scope": "/",
        "display": "standalone",
        "lang": settings.default_language,
        "theme_color": THEME_COLOR,
        "background_color": BACKGROUND_COLOR,
        "icons": [
            {"src": f"{icons}/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": f"{icons}/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": f"{icons}/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return JSONResponse(data, media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
def service_worker():
    # Vanaf de root geserveerd, zodat de service worker de hele site dekt (scope "/").
    # no-cache: de browser controleert bij elk bezoek of er een nieuwe versie is.
    return FileResponse(
        STATIC_DIR / "js" / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/offline", include_in_schema=False)
def offline(request: Request):
    return render(request, "offline.html", request_language(request))


@router.get("/badge", include_in_schema=False)
def badge(user: User = Depends(logged_in_user), db: Session = Depends(get_db)):
    """Aantal taken dat op deze gebruiker wacht, voor de teller op het app-icoon."""
    count = my_task_count(db, user) if user.is_staff else 0
    return JSONResponse({"count": count}, headers={"Cache-Control": "no-store"})
