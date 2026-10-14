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


def write_backup(base, **data):
    (base / "status" / "backup.json").write_text(json.dumps(data))


def test_backup_status_on_update_page_and_dashboard(client, staff, update_dir):
    from datetime import UTC, datetime, timedelta

    write_status(update_dir)
    login(client, "boekhouder@example.org")
    assert "deploy/backup.sh setup" in client.get("/portal/update").text
    assert "back-up werkt niet" not in client.get("/portal").text

    now = datetime.now(UTC).isoformat()
    write_backup(update_dir, state="ok", message="", at=now, file="declaratietool-x.tar.gz.gpg", size=2_500_000)
    page = client.get("/portal/update").text
    assert "laatste back-up is gelukt" in page and "declaratietool-x.tar.gz.gpg" in page
    assert "back-up werkt niet" not in client.get("/portal").text

    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    write_backup(update_dir, state="ok", message="", at=old, file="declaratietool-x.tar.gz.gpg", size=1)
    assert "te lang geleden" in client.get("/portal/update").text
    assert "back-up werkt niet" in client.get("/portal").text

    write_backup(update_dir, state="failed", message="error", at=now, file="", size=0)
    assert "back-up is mislukt" in client.get("/portal/update").text
    assert "back-up werkt niet" in client.get("/portal").text

    # Alleen beheerders krijgen de waarschuwing.
    client.post("/logout")
    login(client, "voorzitter@example.org")
    assert "back-up werkt niet" not in client.get("/portal").text


def test_menu_shows_mark_when_update_available(client, staff, update_dir):
    login(client, "boekhouder@example.org")
    assert "alert-dot" not in client.get("/portal").text  # nog geen status.json

    write_status(update_dir)
    page = client.get("/portal").text
    assert page.count('class="alert-dot"') == 2  # bij Instellingen en bij Updates
    assert "Nieuwe versie beschikbaar" in page

    write_status(update_dir, latest={"sha": "a" * 40, "date": None, "subject": "Oude versie"}, new_commits=[])
    assert "alert-dot" not in client.get("/portal").text

    (update_dir / "status" / "status.json").write_text("kapot")
    assert client.get("/portal").status_code == 200


def test_no_mark_for_board_members(client, staff, update_dir):
    write_status(update_dir)
    login(client, "voorzitter@example.org")
    assert "alert-dot" not in client.get("/portal").text
