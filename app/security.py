"""Wachtwoorden hashen en IBAN's controleren."""

import base64
import hashlib
import hmac
import re
import secrets

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def normalize_iban(iban: str) -> str:
    return re.sub(r"\s+", "", iban or "").upper()


def is_valid_iban(iban: str) -> bool:
    """Controle volgens ISO 13616 (mod-97)."""
    value = normalize_iban(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", value):
        return False
    rearranged = value[4:] + value[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


def format_iban(iban: str) -> str:
    value = normalize_iban(iban)
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))


def parse_amount(text: str) -> int | None:
    """'12,50', '12.50', '€ 1.234,56' -> centen. Geeft None bij ongeldige invoer."""
    value = (text or "").replace("€", "").replace(" ", "").strip()
    if not value:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        cents = round(float(value) * 100)
    except ValueError:
        return None
    return cents if cents > 0 else None
