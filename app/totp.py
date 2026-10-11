"""Tweestapsverificatie: met een authenticator-app (TOTP, RFC 6238) of een code per e-mail.

De app-variant werkt met elke standaard-app: Google Authenticator, Microsoft
Authenticator, Bitwarden, 1Password, Aegis, enz. Herstelcodes en e-mailcodes
worden alleen gehasht bewaard.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import segno

DIGITS = 6
PERIOD = 30
# Eén stap speling voor en na: een klok die tot 30 seconden afwijkt werkt nog.
WINDOW = 1
RECOVERY_CODE_COUNT = 10
EMAIL_CODE_VALID = timedelta(minutes=10)
EMAIL_CODE_RESEND_AFTER = timedelta(seconds=60)


def new_secret() -> str:
    """160 bits willekeurig, in base32 zoals authenticator-apps verwachten."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_code(secret: str, now: float | None = None) -> str:
    return _code_at(secret, int((now if now is not None else time.time()) // PERIOD))


def verify(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int | None:
    """Controleer een code. Geeft de gebruikte tijdstap terug, of None.

    Een code die al eens gebruikt is (stap <= last_step) wordt geweigerd,
    zodat iemand die meekijkt dezelfde code niet nog eens kan gebruiken.
    """
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if not secret or len(code) != DIGITS:
        return None
    step = int((now if now is not None else time.time()) // PERIOD)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if candidate > last_step and hmac.compare_digest(_code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}"


def qr_svg(uri: str) -> str:
    """QR-code als data-URI (SVG), zodat de pagina geen extern plaatje nodig heeft."""
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


def format_secret(secret: str) -> str:
    """In groepjes van vier, makkelijker over te typen."""
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


# ---------------------------------------------------------------- herstelcodes


def _normalize_recovery(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(_normalize_recovery(code).encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], str]:
    """Nieuwe herstelcodes: (leesbare codes voor de gebruiker, opgeslagen hashes)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # zonder letters die op elkaar lijken
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, ",".join(_hash_recovery(c) for c in codes)


def use_recovery_code(stored: str, code: str) -> str | None:
    """Klopt de herstelcode? Dan de opgeslagen hashes zonder deze code (eenmalig bruikbaar), anders None."""
    if len(_normalize_recovery(code)) != 10:
        return None
    wanted = _hash_recovery(code)
    hashes = [h for h in (stored or "").split(",") if h]
    for h in hashes:
        if hmac.compare_digest(h, wanted):
            hashes.remove(h)
            return ",".join(hashes)
    return None


def recovery_codes_left(stored: str) -> int:
    return len([h for h in (stored or "").split(",") if h])


# ---------------------------------------------------------------- code per e-mail


def _hash_email_code(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def new_email_code(user) -> str:
    """Maak een nieuwe code van 6 cijfers voor deze gebruiker; alleen de hash wordt opgeslagen."""
    code = str(secrets.randbelow(10**DIGITS)).zfill(DIGITS)
    user.email_code_hash = _hash_email_code(user.id, code)
    user.email_code_sent_at = datetime.now(UTC)
    return code


def can_resend_email_code(user) -> bool:
    sent = user.email_code_sent_at
    if sent is None:
        return True
    if sent.tzinfo is None:  # SQLite bewaart geen tijdzone
        sent = sent.replace(tzinfo=UTC)
    return datetime.now(UTC) - sent >= EMAIL_CODE_RESEND_AFTER


def use_email_code(user, code: str) -> bool:
    """Klopt de gemailde code en is hij nog geldig? Dan is hij daarna verbruikt."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    sent = user.email_code_sent_at
    if not user.email_code_hash or sent is None or len(code) != DIGITS:
        return False
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=UTC)
    if datetime.now(UTC) - sent > EMAIL_CODE_VALID:
        return False
    if not hmac.compare_digest(user.email_code_hash, _hash_email_code(user.id, code)):
        return False
    user.email_code_hash = ""
    return True
