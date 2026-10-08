"""FastAPI-applicatie."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .routes import auth, helppage, portal, public
from .web import LoginRequired

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.secure_cookies,
        max_age=60 * 60 * 12,
    )
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
        return RedirectResponse("/indienen", status_code=303)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    return app


app = create_app()
