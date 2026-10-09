"""Mailinstellingen (SMTP en IMAP): uit de database, met .env als terugval.

Een beheerder kan de instellingen in het portaal invullen (Mailinstellingen). Die worden
in de tabel key_values bewaard onder 'mail.<veld>' en gaan vóór de waarden uit .env.
Wachtwoorden worden versleuteld opgeslagen met een sleutel die is afgeleid van SECRET_KEY.
De mailer en de worker lezen de instellingen bij elk gebruik, dus een herstart is niet nodig.
"""

import base64
import hashlib
import imaplib
import logging
import smtplib
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import KeyValue

log = logging.getLogger(__name__)

PREFIX = "mail."
TEXT_FIELDS = ("smtp_host", "smtp_user", "mail_from", "imap_host", "imap_user", "imap_folder")
INT_FIELDS = ("smtp_port", "imap_port")
BOOL_FIELDS = ("smtp_starttls", "smtp_ssl")
SECRET_FIELDS = ("smtp_password", "imap_password")
ALL_FIELDS = TEXT_FIELDS + INT_FIELDS + BOOL_FIELDS + SECRET_FIELDS

TEST_TIMEOUT = 15


@dataclass
class MailConfig:
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    mail_from: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    # Velden die uit de database komen in plaats van uit .env (voor de beheerpagina).
    from_db: set[str] = field(default_factory=set)


# ---------------------------------------------------------------- versleuteling


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"declaratietool-mail:" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    """None als het niet lukt, bijvoorbeeld omdat SECRET_KEY is veranderd."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ---------------------------------------------------------------- laden en opslaan


def from_env() -> MailConfig:
    s = get_settings()
    return MailConfig(**{name: getattr(s, name) for name in ALL_FIELDS})


def _stored(db: Session) -> dict[str, str]:
    rows = db.scalars(select(KeyValue).where(KeyValue.key.startswith(PREFIX))).all()
    return {row.key.removeprefix(PREFIX): row.value for row in rows}


def load(db: Session | None = None) -> MailConfig:
    """De geldende instellingen. Zonder db wordt kort een eigen sessie geopend."""
    if db is None:
        from .db import new_session

        try:
            db = new_session()
            try:
                return load(db)
            finally:
                db.close()
        except Exception:  # bijvoorbeeld een database die (nog) niet bereikbaar is
            log.exception("Mailinstellingen uit de database lezen mislukt; .env wordt gebruikt")
            return from_env()

    config = from_env()
    for name, raw in _stored(db).items():
        if name not in ALL_FIELDS:
            continue
        if name in SECRET_FIELDS:
            value = decrypt(raw)
            if value is None:
                log.warning("Opgeslagen %s kan niet worden ontsleuteld (SECRET_KEY gewijzigd?); .env wordt gebruikt", name)
                continue
        elif name in INT_FIELDS:
            value = int(raw)
        elif name in BOOL_FIELDS:
            value = raw == "1"
        else:
            value = raw
        setattr(config, name, value)
        config.from_db.add(name)
    return config


def _put(db: Session, name: str, value: str) -> None:
    key = PREFIX + name
    row = db.get(KeyValue, key)
    if row is None:
        db.add(KeyValue(key=key, value=value))
    else:
        row.value = value


def save(db: Session, config: MailConfig, keep_passwords: bool = True) -> None:
    """Sla alle velden op. Met keep_passwords blijft een leeg wachtwoord ongewijzigd."""
    for name in TEXT_FIELDS:
        _put(db, name, getattr(config, name))
    for name in INT_FIELDS:
        _put(db, name, str(getattr(config, name)))
    for name in BOOL_FIELDS:
        _put(db, name, "1" if getattr(config, name) else "0")
    for name in SECRET_FIELDS:
        value = getattr(config, name)
        if value or not keep_passwords:
            _put(db, name, encrypt(value))


def reset(db: Session) -> None:
    """Verwijder alle opgeslagen mailinstellingen; daarna gelden weer de waarden uit .env."""
    for row in db.scalars(select(KeyValue).where(KeyValue.key.startswith(PREFIX))).all():
        db.delete(row)


# ---------------------------------------------------------------- verbinding testen


def smtp_connect(config: MailConfig, timeout: int = 30) -> smtplib.SMTP:
    """Open een (ingelogde) SMTP-verbinding volgens de instellingen."""
    if config.smtp_ssl:
        server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=timeout)
    else:
        server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=timeout)
    try:
        if config.smtp_starttls and not config.smtp_ssl:
            server.starttls()
        if config.smtp_user:
            server.login(config.smtp_user, config.smtp_password)
    except Exception:
        server.close()
        raise
    return server


def imap_connect(config: MailConfig, timeout: int | None = None) -> imaplib.IMAP4_SSL:
    """Open een ingelogde IMAP-verbinding en kies de map."""
    imap = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=timeout)
    try:
        imap.login(config.imap_user, config.imap_password)
        status, _ = imap.select(config.imap_folder)
        if status != "OK":
            raise imaplib.IMAP4.error(f"map '{config.imap_folder}' niet gevonden")
    except Exception:
        imap.logout()
        raise
    return imap


def check_smtp(config: MailConfig) -> tuple[bool, str]:
    """Verbinden en inloggen, zonder iets te versturen. Geeft (gelukt, foutmelding)."""
    if not config.smtp_host:
        return False, "no_host"
    try:
        with smtp_connect(config, timeout=TEST_TIMEOUT) as server:
            server.noop()
    except Exception as exc:
        return False, _describe(exc)
    return True, ""


def check_imap(config: MailConfig) -> tuple[bool, str]:
    """Verbinden, inloggen en de map openen. Bij succes het aantal ongelezen mails."""
    if not config.imap_host:
        return False, "no_host"
    try:
        imap = imap_connect(config, timeout=TEST_TIMEOUT)
        try:
            status, data = imap.search(None, "UNSEEN")
            unseen = len(data[0].split()) if status == "OK" and data and data[0] else 0
        finally:
            imap.logout()
    except Exception as exc:
        return False, _describe(exc)
    return True, str(unseen)


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]
