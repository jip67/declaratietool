import json

import pytest

from app.config import get_settings

from .conftest import login


@pytest.fixture
def update_dir(tmp_path, monkeypatch):
    base = tmp_path / "update"
    (base / "requests").mkdir(parents=True)
    (base / "status").mkdir()
    monkeypatch.setenv("UPDATE_DIR", str(base))
    monkeypatch.setenv("APP_VERSION", "a" * 40)
    get_settings.cache_clear()
    return base


def write_status(base, **extra):
    data = {
        "state": "idle",
        "message": "",
        "current": {"sha": "a" * 40, "date": "2026-10-08T10:00:00+02:00", "subject": "Oude versie"},
        "latest": {"sha": "b" * 40, "date": "2026-10-09T10:00:00+02:00", "subject": "Nieuwe versie"},
        "new_commits": [{"sha": "bbbbbbb", "subject": "Nieuwe versie"}],
        "started_at": None,
        "updated_at": "2026-10-09T08:00:00+00:00",
    }
    data.update(extra)
    (base / "status" / "status.json").write_text(json.dumps(data))


def test_only_admin_sees_update_page(client, staff, update_dir):
    login(client, "voorzitter@example.org")
    assert "/portal/update" not in client.get("/portal").text
    assert client.get("/portal/update").status_code == 403
    assert client.post("/portal/update", data={"action": "update"}).status_code == 403
    assert not (update_dir / "requests" / "request").exists()


def test_shows_versions_and_requests_update(client, staff, update_dir):
    write_status(update_dir)
    login(client, "boekhouder@example.org")
    assert "/portal/update" in client.get("/portal").text
    page = client.get("/portal/update")
    assert page.status_code == 200
    assert "Oude versie" in page.text and "Nieuwe versie" in page.text and "aaaaaaa" in page.text

    r = client.post("/portal/update", data={"action": "update"}, follow_redirects=False)
    assert r.status_code == 303
    assert (update_dir / "requests" / "request").read_text() == "update\n"

    # Terwijl het verzoek loopt: geen tweede verzoek, pagina ververst vanzelf.
    page = client.get("/portal/update")
    assert 'http-equiv="refresh"' in page.text
    r = client.post("/portal/update", data={"action": "check"}, follow_redirects=False)
    assert r.headers["location"].endswith("error=update.busy")
    assert (update_dir / "requests" / "request").read_text() == "update\n"


def test_up_to_date_and_failed_log(client, staff, update_dir):
    write_status(update_dir, state="failed", latest={"sha": "a" * 40, "date": None, "subject": "Oude versie"}, new_commits=[])
    (update_dir / "status" / "update.log").write_text("error: merge conflict\n")
    login(client, "boekhouder@example.org")
    page = client.get("/portal/update").text
    assert "nieuwste versie" in page and "merge conflict" in page and "mislukt" in page


def test_unknown_action_and_not_configured(client, staff, tmp_path, monkeypatch):
    monkeypatch.setenv("UPDATE_DIR", str(tmp_path / "bestaat-niet"))
    get_settings.cache_clear()
    login(client, "boekhouder@example.org")
    assert "niet ingesteld" in client.get("/portal/update").text
    assert client.post("/portal/update", data={"action": "rm -rf"}).status_code == 400
    r = client.post("/portal/update", data={"action": "update"}, follow_redirects=False)
    assert r.headers["location"].endswith("error=update.not_configured")
