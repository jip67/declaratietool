"""Meldingen per e-mail voor bestuursleden en beheerders.

Iedereen met een bestuursrol kiest zelf, onder Instellingen → Meldingen, welke mails hij wil krijgen:
bij een nieuwe declaratie, bij elke statuswijziging en wanneer een taak langer dan een zelf gekozen
aantal dagen openstaat. Beheerders kunnen daarnaast meldingen krijgen bij een geslaagde login, bij
een tijdelijke inlogblokkering en bij binnengekomen mail. De keuzes staan per gebruiker in
users.notify en staan standaard uit. Iedereen krijgt de mail in de eigen taal. Een mislukte melding
mag inloggen, het verwerken van mail of een stap in de declaratie nooit hinderen.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import mailer
from .config import get_settings
from .i18n import translate
from .models import OPEN_STATUSES, ROLE_FOR_STATUS, Claim, OverdueNotice, Role, User, utcnow

log = logging.getLogger(__name__)

# Voor alle bestuursleden (voorzitter, boekhouder, secretaris, beheerder).
STAFF_KINDS = ("new_claim", "status", "overdue")
# Alleen voor beheerders.
ADMIN_KINDS = ("login", "lockout", "mail")
KINDS = STAFF_KINDS + ADMIN_KINDS
DEFAULT_OVERDUE_DAYS = 3
MAX_OVERDUE_DAYS = 365


def kinds_for(user: User) -> tuple[str, ...]:
    """De meldingen die deze gebruiker kan aanzetten."""
    kinds: tuple[str, ...] = STAFF_KINDS if user.is_staff else ()
    if user.has_role(Role.ADMIN):
        kinds += ADMIN_KINDS
    return kinds


def load(user: User) -> dict[str, bool]:
    chosen = set(user.notify.split(",")) if user.notify else set()
    return {kind: kind in chosen for kind in kinds_for(user)}


def save(user: User, choices: dict[str, bool], overdue_days: int | None = None) -> None:
    user.notify = ",".join(kind for kind in kinds_for(user) if choices.get(kind))
    if overdue_days is not None:
        user.notify_overdue_days = min(max(overdue_days, 1), MAX_OVERDUE_DAYS)


def wants(user: User, kind: str) -> bool:
    return kind in kinds_for(user) and load(user)[kind]


def recipients(db: Session, kind: str, exclude: set[int] | None = None) -> list[User]:
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
    return [u for u in users if wants(u, kind) and u.id not in (exclude or set())]


def _send(db: Session, kind: str, users: list[User] | None = None, background: BackgroundTasks | None = None,
          translated: dict[str, str] | None = None, per_user=None, rollback: bool = True, **values) -> None:
    """translated: velden waarvan de waarde een vertaalsleutel is, per ontvanger vertaald.
    per_user: functie (taal) -> extra velden, voor tekst die per taal anders is.

    Met background gaat de mail pas na het antwoord aan de browser de deur uit, zodat een
    trage mailserver het inloggen niet ophoudt. rollback=False midden in een stap van een
    declaratie: een mislukte melding mag die stap niet terugdraaien.
    """
    try:
        if users is None:
            users = recipients(db, kind)
        if not users:
            return
        from .workflow import local_time

        settings = get_settings()
        values = {"app": settings.app_name, "when": local_time(utcnow()), "url": settings.base_url, **values}
        for user in users:
            values.update({k: translate(v, user.language) for k, v in (translated or {}).items()})
            if per_user is not None:
                values.update(per_user(user.language))
            mail = mailer.Mail(
                to=[user.email],
                subject=translate(f"notify.{kind}.subject", user.language, **values),
                body=translate(f"notify.{kind}.body", user.language, name=user.name, **values),
            )
            if background is None:
                mailer.send(mail)
            else:
                background.add_task(mailer.send, mail)
    except Exception:
        if rollback:
            db.rollback()
        log.exception("Melding '%s' versturen mislukt", kind)


def login(db: Session, user: User, ip: str, user_agent: str, background: BackgroundTasks | None = None) -> None:
    _send(db, "login", background=background, user=f"{user.name} <{user.email}>", ip=ip, browser=user_agent or "-")


def lockout(db: Session, email: str, ip: str, by_ip: bool, background: BackgroundTasks | None = None) -> None:
    """Een tijdelijke blokkering is net ingegaan, op het e-mailadres of op het IP-adres."""
    reason = "notify.lockout.by_ip" if by_ip else "notify.lockout.by_account"
    _send(db, "lockout", background=background, translated={"reason": reason}, email=email, ip=ip)


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


# ---------------------------------------------------------------- declaraties


def _claim_values(claim: Claim) -> dict:
    from .workflow import portal_link

    return {"reference": claim.reference, "link": portal_link(claim)}


def _summary(claim: Claim):
    from .workflow import claim_summary

    return lambda lang: {"summary": claim_summary(claim, lang)}


def new_claim(db: Session, claim: Claim, actor: User | None = None) -> None:
    """Er is een declaratie binnengekomen (per mail of via het portaal)."""
    try:
        exclude = {actor.id} if actor else set()
        _send(db, "new_claim", recipients(db, "new_claim", exclude), rollback=False,
              translated={"status": f"status.{claim.status}", "source": f"notify.source.{claim.source}"},
              per_user=_summary(claim), attachments=len(claim.attachments), **_claim_values(claim))
    except Exception:
        log.exception("Melding 'new_claim' versturen mislukt")


def status_changed(db: Session, claim: Claim, action: str, actor: User | None = None) -> None:
    """De status van een declaratie is veranderd; action is de stap uit het logboek (event.<action>).

    Wie de stap zelf zette krijgt geen melding, en wie nu aan zet is ook niet: die krijgt al
    een mail met de taak.
    """
    def extra(lang: str) -> dict:
        reason = ""
        if claim.rejection_reason:
            reason = translate("mail.status.reason", lang, reason=claim.rejection_reason)
        by = actor.name if actor else (claim.submitter.name or claim.submitter.email)
        return {**_summary(claim)(lang), "reason": reason, "by": by}

    try:
        exclude = {actor.id} if actor else set()
        role = ROLE_FOR_STATUS.get(claim.status_enum)
        users = [u for u in recipients(db, "status", exclude) if role is None or not u.has_role(role)]
        _send(db, "status", users, rollback=False,
              translated={"status": f"status.{claim.status}", "event": f"event.{action}"},
              per_user=extra, **_claim_values(claim))
    except Exception:
        log.exception("Melding 'status' versturen mislukt")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def overdue(db: Session, now: datetime | None = None) -> int:
    """Meldt taken die langer openstaan dan het aantal dagen dat iemand koos.

    Per gebruiker één mail met alle taken die net over de grens gingen; elke taak wordt maar
    één keer gemeld. Geeft het aantal verstuurde mails terug.
    """
    sent = 0
    try:
        now = now or utcnow()
        open_values = [s.value for s in OPEN_STATUSES]
        claims = db.scalars(select(Claim).where(Claim.status.in_(open_values)).order_by(Claim.id)).all()
        # Meldingen over afgehandelde of verwijderde declaraties zijn niet meer nodig.
        db.execute(delete(OverdueNotice).where(
            OverdueNotice.claim_id.not_in(select(Claim.id).where(Claim.status.in_(open_values)))))
        for user in recipients(db, "overdue"):
            notices = {n.claim_id: n for n in db.scalars(select(OverdueNotice).where(OverdueNotice.user_id == user.id))}
            limit = timedelta(days=user.notify_overdue_days)
            due = []
            for claim in claims:
                since = _aware(claim.status_changed_at)
                if now - since < limit:
                    continue
                notice = notices.get(claim.id)
                if notice is not None and abs(_aware(notice.since) - since) < timedelta(seconds=1):
                    continue  # deze taak is al gemeld
                if notice is None:
                    db.add(OverdueNotice(user_id=user.id, claim_id=claim.id, since=since))
                else:
                    notice.since = since
                due.append(claim)
            if not due:
                continue
            _send(db, "overdue", [user], rollback=False, per_user=lambda lang, due=due: {"list": _overdue_lines(due, now, lang)},
                  count=len(due), days=user.notify_overdue_days, overview=f"{get_settings().base_url}/portal")
            sent += 1
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Meldingen over openstaande taken versturen mislukt")
    return sent


def _overdue_lines(claims: list[Claim], now: datetime, lang: str) -> str:
    from .workflow import portal_link

    lines = []
    for claim in claims:
        role = ROLE_FOR_STATUS.get(claim.status_enum)
        waiting = translate(f"role.{role.value}", lang) if role else translate("notify.overdue.submitter", lang)
        days = (now - _aware(claim.status_changed_at)).days
        lines.append(
            f"- {claim.reference} | {claim.amount_display} | {translate(f'status.{claim.status}', lang)} | "
            f"{translate('notify.overdue.waiting', lang, who=waiting, days=days)} | {portal_link(claim)}"
        )
    return "\n".join(lines)
