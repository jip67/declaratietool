"""Bijwerken via het portaal.

De app werkt zichzelf niet bij: hij heeft bewust geen toegang tot Docker. Hij legt
alleen een verzoek neer in UPDATE_DIR/requests; deploy/updater.sh op de server voert
het uit en schrijft de uitkomst naar UPDATE_DIR/status/status.json (alleen-lezen voor
de app).
"""

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import get_settings

log = logging.getLogger(__name__)

ACTIONS = {"check", "update"}


def _dir() -> Path:
    return Path(get_settings().update_dir)


def _request_file() -> Path:
    return _dir() / "requests" / "request"


def available() -> bool:
    """Is de updater op de server ingesteld (map aanwezig en schrijfbaar)?"""
    requests = _dir() / "requests"
    return requests.is_dir() and os.access(requests, os.W_OK)


def pending() -> str | None:
    """Een verzoek dat de updater nog niet heeft opgepakt."""
    try:
        return _request_file().read_text().strip() or None
    except OSError:
        return None


def status() -> dict:
    try:
        data = json.loads((_dir() / "status" / "status.json").read_text())
    except (OSError, ValueError):
        return {}
    data["updated_at"] = _parse_time(data.get("updated_at"))
    data["started_at"] = _parse_time(data.get("started_at"))
    for key in ("current", "latest"):
        if isinstance(data.get(key), dict):
            data[key]["date"] = _parse_time(data[key].get("date"))
    return data


# Draait de nachtelijke back-up langer dan dit niet, dan waarschuwt het portaal.
BACKUP_MAX_AGE = timedelta(hours=36)


def backup_status() -> dict:
    """Uitkomst van de laatste back-up, door deploy/backup.sh in status/backup.json gezet.

    Leeg als de back-up nooit heeft gedraaid. 'stale' is waar als de laatste geslaagde
    back-up te oud is, bijvoorbeeld omdat de timer niet loopt.
    """
    try:
        data = json.loads((_dir() / "status" / "backup.json").read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    data["at"] = _parse_time(data.get("at"))
    data["stale"] = data.get("state") == "ok" and (
        data["at"] is None or datetime.now(UTC) - data["at"] > BACKUP_MAX_AGE
    )
    return data


def backup_needs_attention(data: dict | None = None) -> bool:
    data = backup_status() if data is None else data
    return bool(data) and (data.get("state") != "ok" or data["stale"])


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def log_tail(lines: int = 40) -> str:
    try:
        text = (_dir() / "status" / "update.log").read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def running_version() -> str:
    return get_settings().app_version


def is_busy(current: dict | None = None) -> bool:
    current = status() if current is None else current
    return pending() is not None or current.get("state") == "running"


def update_available(current: dict) -> bool:
    latest, now = current.get("latest"), current.get("current")
    return bool(latest and now and latest["sha"] != now["sha"] and current.get("new_commits"))


def request(action: str, requested_by: str) -> None:
    if action not in ACTIONS:
        raise ValueError(action)
    tmp = _request_file().with_name(".request.tmp")
    tmp.write_text(action + "\n")
    tmp.replace(_request_file())
    log.info("Verzoek '%s' voor de updater door %s", action, requested_by)
