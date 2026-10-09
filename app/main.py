"""FastAPI-applicatie."""

import logging

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .routes import auth, helppage, portal, public
from .web import LoginRequired

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Alleen eigen bestanden laden; geen inline scripts, geen inbedden op andere sites.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data: blob:; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def check_secret_key(settings) -> None:
    """Weiger te starten met een zwakke sleutel: daarmee kan iemand een inlogsessie vervalsen."""
    key = settings.secret_key or ""
    if settings.secure_cookies and (len(key) < 32 or key == "verander-mij"):
        raise RuntimeError(
            "SECRET_KEY in .env ontbreekt of is te kort. Maak er een met:  openssl rand -hex 32"
        )


def cross_site(request: Request) -> bool:
    """Een formulier dat vanaf een andere website naar ons wordt verstuurd (CSRF)."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        return True
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return urlsplit(origin).netloc != request.headers.get("host", "")
    return False


def create_app() -> FastAPI:
    settings = get_settings()
    check_secret_key(settings)
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.secure_cookies,
        max_age=60 * 60 * 12,
    )

    @app.middleware("http")
    async def _security(request: Request, call_next):
        if request.method in UNSAFE_METHODS and cross_site(request):
            return PlainTextResponse("Forbidden", status_code=403)
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # Persoonlijke links (/c/...) mogen niet via de Referer naar andere sites lekken.
        headers.setdefault("Referrer-Policy", "same-origin")
        # Niet in zoekmachines opnemen.
        headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        if headers.get("content-type", "").startswith("text/html"):
            headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(public.router)
    app.include_router(auth.router)
    app.include_router(portal.router)
    app.include_router(helppage.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse("/portal", status_code=303)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    return app


app = create_app()
