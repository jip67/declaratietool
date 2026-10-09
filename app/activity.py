"""Logboek voor de beheerder: inlogpogingen en binnengekomen mail.

Regels worden na LOG_RETENTION_DAYS dagen automatisch verwijderd door de worker.
"""

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Claim, IncomingMail, LoginAttempt, User, utcnow

log = logging.getLogger(__name__)

LOGIN_REASONS = ("unknown_user", "wrong_password", "inactive", "locked")


def record_login(
    db: Session, email: str, ip: str, user_agent: str, user: User | None = None, reason: str = ""
) -> None:
    """Legt een inlogpoging vast. Zonder reason is het een geslaagde login."""
    db.add(
        LoginAttempt(
            email=email[:255],
            user_id=user.id if user else None,
            success=not reason,
            reason=reason,
            ip=ip[:64],
            user_agent=user_agent[:255],
        )
    )
    db.commit()


def record_mail(db: Session, sender: str, subject: str, attachments: int, result: str, claim: Claim | None = None) -> None:
    db.add(
        IncomingMail(
            sender=sender[:255],
            subject=subject[:255],
            attachments=attachments,
            result=result[:64],
            claim_id=claim.id if claim else None,
        )
    )
    db.commit()


def recent_error(db: Session, sender: str, subject: str) -> bool:
    since = utcnow() - timedelta(days=1)
    query = select(IncomingMail.id).where(
        IncomingMail.result == "error",
        IncomingMail.sender == sender[:255],
        IncomingMail.subject == subject[:255],
        IncomingMail.at >= since,
    )
    return db.scalar(query.limit(1)) is not None


def purge(db: Session) -> int:
    """Verwijdert logregels ouder dan de bewaartermijn. Geeft het aantal verwijderde regels terug."""
    days = get_settings().log_retention_days
    if days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    removed = db.execute(delete(LoginAttempt).where(LoginAttempt.at < cutoff)).rowcount
    removed += db.execute(delete(IncomingMail).where(IncomingMail.at < cutoff)).rowcount
    db.commit()
    if removed:
        log.info("%s oude logregels verwijderd", removed)
    return removed
