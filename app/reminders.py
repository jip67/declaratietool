"""Dagelijkse herinneringen voor openstaande taken."""

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mailer, workflow
from .config import get_settings
from .i18n import translate
from .models import ROLE_FOR_STATUS, Claim, KeyValue, Status, utcnow

log = logging.getLogger(__name__)

LAST_RUN_KEY = "reminders_last_run"
# Wie vandaag pas een taak kreeg, heeft al een bericht gehad.
MIN_AGE = timedelta(hours=12)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def send_reminders(db: Session) -> int:
    """Stuurt herinneringen. Geeft het aantal verstuurde mails terug."""
    settings = get_settings()
    now = utcnow()
    sent = 0
    claims = db.scalars(select(Claim).where(Claim.status.in_([s.value for s in ROLE_FOR_STATUS] + [Status.RECEIVED.value]))).all()

    per_user: dict[int, list[Claim]] = defaultdict(list)
    users = {}
    for claim in claims:
        if now - _aware(claim.status_changed_at) < MIN_AGE:
            continue
        if claim.status_enum == Status.RECEIVED:
            if now - _aware(claim.created_at) > timedelta(days=settings.submitter_reminder_days):
                continue
            s = claim.submitter
            mailer.send(
                mailer.Mail(
                    to=[s.email],
                    subject=translate("mail.reminder_submitter.subject", s.language, reference=claim.reference),
                    body=translate(
                        "mail.reminder_submitter.body",
                        s.language,
                        name=s.name or s.email,
                        link=workflow.claim_link(claim),
                        org=settings.organisation_name,
                    ),
                )
            )
            sent += 1
            continue
        for user in workflow.users_with_role(db, ROLE_FOR_STATUS[claim.status_enum]):
            users[user.id] = user
            per_user[user.id].append(claim)

    for user_id, user_claims in per_user.items():
        user = users[user_id]
        lines = [
            f"- {c.reference} | {c.amount_display} | {translate('task.' + ROLE_FOR_STATUS[c.status_enum].value, user.language)} | {workflow.portal_link(c)}"
            for c in user_claims
        ]
        mailer.send(
            mailer.Mail(
                to=[user.email],
                subject=translate("mail.reminder.subject", user.language, count=len(user_claims)),
                body=translate(
                    "mail.reminder.body",
                    user.language,
                    name=user.name,
                    list="\n".join(lines),
                    link=f"{settings.base_url}/portal",
                ),
            )
        )
        sent += 1
    log.info("Herinneringen verstuurd: %s", sent)
    return sent


def run_if_due(db: Session) -> bool:
    """Voert de herinneringsronde één keer per dag uit, vanaf reminder_hour (lokale tijd)."""
    settings = get_settings()
    local_now = datetime.now(ZoneInfo(settings.timezone))
    if local_now.hour < settings.reminder_hour:
        return False
    today = local_now.date().isoformat()
    record = db.get(KeyValue, LAST_RUN_KEY)
    if record is not None and record.value == today:
        return False
    send_reminders(db)
    if record is None:
        db.add(KeyValue(key=LAST_RUN_KEY, value=today))
    else:
        record.value = today
    db.commit()
    return True
