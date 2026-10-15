from pathlib import Path

from app.config import get_settings

STATIC = Path(__file__).parent.parent / "app" / "static"


def test_manifest_makes_the_site_installable(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    data = r.json()
    assert data["short_name"] == get_settings().app_name
    assert data["start_url"] == "/portal"
    assert data["display"] == "standalone"
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i["purpose"] == "maskable" for i in data["icons"])
    for icon in data["icons"]:
        assert client.get(icon["src"]).status_code == 200


def test_service_worker_is_served_from_the_root(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-cache"


def test_service_worker_precaches_only_existing_public_files(client):
    import re

    source = (STATIC / "js" / "sw.js").read_text()
    paths = re.findall(r'"(/[^"]*)"', source.split("PRECACHE = [")[1].split("]")[0])
    assert "/offline" in paths
    for path in paths:
        assert not path.startswith(("/portal", "/c/")), "geen persoonlijke pagina's bewaren"
        assert client.get(path).status_code == 200, path


def test_pages_link_manifest_and_register_service_worker(client):
    html = client.get("/login").text
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "/static/js/app.js" in html


def test_offline_page_needs_no_login(client):
    r = client.get("/offline?lang=en", follow_redirects=False)
    assert r.status_code == 200
    assert "No connection" in r.text
