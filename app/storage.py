"""Opslag van bijlagen op schijf."""

import mimetypes
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Attachment, Claim

ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def guess_type(filename: str, declared: str | None = None) -> str | None:
    declared = (declared or "").lower().split(";")[0].strip()
    if declared == "image/jpg":
        declared = "image/jpeg"
    if declared in ALLOWED_TYPES:
        return declared
    suffix = Path(filename or "").suffix.lower()
    if suffix in (".heic", ".heif"):
        return "image/" + suffix[1:]
    guessed = mimetypes.guess_type(filename or "")[0]
    return guessed if guessed in ALLOWED_TYPES else None


def safe_filename(name: str) -> str:
    name = Path(name or "bijlage").name
    return re.sub(r"[^\w.\- ]", "_", name)[:200] or "bijlage"


def upload_root() -> Path:
    root = Path(get_settings().upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_attachment(db: Session, claim: Claim, filename: str, content_type: str, data: bytes) -> Attachment:
    folder = upload_root() / str(claim.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{ALLOWED_TYPES[content_type]}"
    path.write_bytes(data)
    att = Attachment(
        claim=claim,
        original_filename=safe_filename(filename),
        stored_path=str(path.relative_to(upload_root())),
        content_type=content_type,
        size=len(data),
    )
    db.add(att)
    return att


def absolute(relative: str) -> Path:
    path = (upload_root() / relative).resolve()
    if upload_root().resolve() not in path.parents:
        raise ValueError("Ongeldig pad")
    return path
