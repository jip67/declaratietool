import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import mailer
from app.config import get_settings
from app.db import Base, get_engine, new_session, reset_engine
from app.models import User
from app.security import hash_password


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("BASE_URL", "http://testserver")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("IMAP_HOST", "")
    monkeypatch.setenv("MAIL_FROM", "declaraties@example.org")
    get_settings.cache_clear()
    reset_engine()
    Base.metadata.create_all(get_engine())
    mailer.outbox.clear()
    from app.routes import auth

    auth._failures.clear()
    yield
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def db():
    session = new_session()
    yield session
    session.close()


@pytest.fixture
def client():
    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def staff(db):
    users = {
        "chair": User(email="voorzitter@example.org", name="Vera Voorzitter", password_hash=hash_password("geheim12345"), roles="chair"),
        "treasurer": User(email="boekhouder@example.org", name="Bob Boekhouder", password_hash=hash_password("geheim12345"), roles="treasurer,admin"),
        "secretary": User(email="secretaris@example.org", name="Sam Secretaris", password_hash=hash_password("geheim12345"), roles="secretary"),
    }
    db.add_all(users.values())
    db.commit()
    return users


def login(client, email):
    r = client.post("/login", data={"email": email, "password": "geheim12345"}, follow_redirects=False)
    assert r.status_code == 303


def jpeg_bytes(size=(800, 1000)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (240, 240, 230)).save(buf, "JPEG")
    return buf.getvalue()


def pdf_bytes() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "Factuur 123")
    c.save()
    return buf.getvalue()
