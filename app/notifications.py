"""Meldingen per e-mail voor de beheerder.

De beheerder kan per soort melding kiezen of hij een mail wil krijgen: bij een geslaagde login,
bij een tijdelijke inlogblokkering en bij binnengekomen mail. De keuzes staan in de tabel
key_values onder 'notify.<soort>' en staan standaard uit. Alle actieve beheerders krijgen de mail,
elk in de eigen taal. Een mislukte melding mag inloggen of het verwerken van mail nooit hinderen.
"""

import logging

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mailer
from .config import get_settings
from .i18n import translate
from .models import Claim, KeyValue, Role, User, utcnow

log = logging.getLogger(__name__)

PREFIX = "notify."
KINDS = ("login", "lockout", "mail")


def load(db: Session) -> dict[str, bool]:
    rows = db.scalars(select(KeyValue).where(KeyValue.key.startswith(PREFIX))).all()
    stored = {row.key.removeprefix(PREFIX): row.value == "1" for row in rows}
    return {kind: stored.get(kind, False) for kind in KINDS}


def save(db: Session, choices: dict[str, bool]) -> None:
    for kind in KINDS:
        key = PREFIX + kind
        value = "1" if choices.get(kind) else "0"
        row = db.get(KeyValue, key)
        if row is None:
            db.add(KeyValue(key=key, value=value))
        else:
            row.value = value


def recipients(db: Session) -> list[User]:
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
    return [u for u in users if u.has_role(Role.ADMIN)]


def _send(db: Session, kind: str, background: BackgroundTasks | None = None,
          translated: dict[str, str] | None = None, **values) -> None:
    """translated: velden waarvan de waarde een vertaalsleutel is, per ontvanger vertaald.

    Met background gaat de mail pas na het antwoord aan de browser de deur uit, zodat een
    trage mailserver het inloggen niet ophoudt.
    """
    try:
        if not load(db)[kind]:
            return
        from .workflow import local_time

        settings = get_settings()
        values = {"app": settings.app_name, "when": local_time(utcnow()), "url": settings.base_url, **values}
        for admin in recipients(db):
            values.update({k: translate(v, admin.language) for k, v in (translated or {}).items()})
            mail = mailer.Mail(
                to=[admin.email],
                subject=translate(f"notify.{kind}.subject", admin.language, **values),
                body=translate(f"notify.{kind}.body", admin.language, name=admin.name, **values),
            )
            if background is None:
                mailer.send(mail)
            else:
                background.add_task(mailer.send, mail)
    except Exception:
        db.rollback()
        log.exception("Melding '%s' versturen mislukt", kind)


def login(db: Session, user: User, ip: str, user_agent: str, background: BackgroundTasks | None = None) -> None:
    _send(db, "login", background, user=f"{user.name} <{user.email}>", ip=ip, browser=user_agent or "-")


def lockout(db: Session, email: str, ip: str, by_ip: bool, background: BackgroundTasks | None = None) -> None:
    """Een tijdelijke blokkering is net ingegaan, op het e-mailadres of op het IP-adres."""
    reason = "notify.lockout.by_ip" if by_ip else "notify.lockout.by_account"
    _send(db, "lockout", background, translated={"reason": reason}, email=email, ip=ip)


def incoming_mail(db: Session, sender: str, subject: str, attachments: int, result: str,
                  claim: Claim | None = None) -> None:
    # Automatische berichten overslaan: anders kan een melding die in de eigen mailbox
    # belandt een kringloop van meldingen veroorzaken.
    if result.startswith("ignored:automatic"):
        return
    kind = result.split(":")[0]
    key = "log.result.created" if kind == "created" else "log.result." + result.replace(":", "_")
    reference = claim.reference if claim else ""
    _send(db, "mail", translated={"outcome": key}, sender=sender or "-", subject=subject or "-",
          attachments=attachments, reference=reference)
