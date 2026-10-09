import pytest

from app.config import get_settings


def test_security_headers(client):
    r = client.get("/login")
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"


def test_form_from_other_site_is_refused(client, staff):
    r = client.post(
        "/login",
        data={"email": "voorzitter@example.org", "password": "geheim12345"},
        headers={"Origin": "https://kwaadaardig.example"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    r = client.post("/logout", headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False)
    assert r.status_code == 403


def test_form_from_own_site_is_allowed(client, staff):
    r = client.post(
        "/login",
        data={"email": "voorzitter@example.org", "password": "geheim12345"},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_password_spraying_from_one_ip_is_slowed_down(client, staff):
    for i in range(20):
        client.post("/login", data={"email": f"iemand{i}@example.org", "password": "fout"})
    r = client.post("/login", data={"email": "voorzitter@example.org", "password": "geheim12345"})
    assert r.status_code == 429


@pytest.mark.parametrize("key", ["", "verander-mij", "kort"])
def test_weak_secret_key_refused_on_https(monkeypatch, key):
    monkeypatch.setenv("BASE_URL", "https://declaraties.example.org")
    monkeypatch.setenv("SECRET_KEY", key)
    get_settings.cache_clear()
    from app.main import create_app

    with pytest.raises(RuntimeError):
        create_app()


def test_strong_secret_key_accepted(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://declaraties.example.org")
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    get_settings.cache_clear()
    from app.main import create_app

    create_app()
