"""Eenvoudige vertalingen. Voeg een taal toe door locales/<code>.json aan te maken."""

import json
from functools import lru_cache
from pathlib import Path

from .config import get_settings

LOCALE_DIR = Path(__file__).parent / "locales"


@lru_cache
def _catalog(lang: str) -> dict[str, str]:
    path = LOCALE_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def available_languages() -> list[str]:
    return sorted(p.stem for p in LOCALE_DIR.glob("*.json"))


def pick_language(*candidates: str | None, accept_language: str | None = None) -> str:
    available = available_languages()
    for lang in candidates:
        if lang and lang in available:
            return lang
    if accept_language:
        for part in accept_language.split(","):
            code = part.split(";")[0].strip().lower()[:2]
            if code in available:
                return code
    return get_settings().default_language


def translate(key: str, lang: str | None = None, **kwargs) -> str:
    lang = lang or get_settings().default_language
    text = _catalog(lang).get(key) or _catalog(get_settings().default_language).get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def translator(lang: str):
    def t(key: str, **kwargs) -> str:
        return translate(key, lang, **kwargs)

    return t
