"""De stappen van een declaratie en de berichten die daarbij horen.

ontvangen -> (indiener vult aan) -> ingediend -> (voorzitter keurt goed + paraaf)
-> goedgekeurd -> (boekhouder zet betaling klaar) -> klaargezet
-> (secretaris voert betaling uit bij de bank) -> betaald

Bij elke stap krijgt de indiener een update en krijgt wie daarna aan zet is een bericht.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import approval_links, mailer, notifications, storage
from .config import get_settings
from .i18n import translate
from .models import ROLE_FOR_STATUS, Claim, Event, Role, Status, Submitter, User, utcnow
from .security import format_iban, normalize_iban
from .stamping import stamp_file, stamp_lines

log = logging.getLogger(__name__)


class WorkflowError(Exception):
    pass


# ---------------------------------------------------------------- helpers


def claim_link(claim: Claim) -> str:
    return f"{get_settings().base_url}/c/{claim.token}"


def portal_link(claim: Claim) -> str:
    return f"{get_settings().base_url}/portal/claims/{claim.id}"


def log_event(db: Session, claim: Claim, action: str, user: User | None = None, note: str = "") -> None:
    db.add(Event(claim=claim, action=action, user_id=user.id if user else None, note=note))


def set_status(claim: Claim, status: Status) -> None:
    claim.status = status.value
    claim.status_changed_at = utcnow()


def assign_reference(db: Session, claim: Claim) -> None:
    db.flush()
    year = utcnow().year
    prefix = f"{get_settings().reference_prefix}{year}-"
    count = db.scalar(select(func.count(Claim.id)).where(Claim.reference.like(prefix + "%"))) or 0
    claim.reference = f"{prefix}{count + 1:04d}"


def users_with_role(db: Session, role: Role) -> list[User]:
    users = db.scalars(select(User).where(User.active.is_(True))).all()
    return [u for u in users if u.has_role(role)]


def get_or_create_submitter(db: Session, email: str, name: str = "", language: str | None = None) -> Submitter:
    email = email.strip().lower()
    submitter = db.scalar(select(Submitter).where(Submitter.email == email))
    if submitter is None:
        submitter = Submitter(
            email=email, name=name.strip(), language=language or get_settings().default_language
        )
        db.add(submitter)
        db.flush()
    elif name and not submitter.name:
        submitter.name = name.strip()
    return submitter


def claim_summary(claim: Claim, lang: str) -> str:
    t = lambda key, **kw: translate(key, lang, **kw)  # noqa: E731
    return "\n".join(
        [
            f"{t('field.reference')}: {claim.reference}",
            f"{t('field.submitter')}: {claim.submitter.name or claim.submitter.email} <{claim.submitter.email}>",
            f"{t('field.amount')}: {claim.amount_display}",
            f"{t('field.description')}: {claim.description}",
            f"{t('field.iban')}: {format_iban(claim.iban)}",
            f"{t('field.account_holder')}: {claim.account_holder}",
        ]
    )


# ---------------------------------------------------------------- berichten


def notify_received(claim: Claim) -> None:
    s = claim.submitter
    lang = s.language
    mailer.send(
        mailer.Mail(
            to=[s.email],
            subject=translate("mail.received.subject", lang, reference=claim.reference),
            body=translate(
                "mail.received.body",
                lang,
                name=s.name or s.email,
                count=len(claim.attachments),
                link=claim_link(claim),
                org=get_settings().organisation_name,
            ),
        )
    )


def notify_submitter_status(claim: Claim) -> None:
    s = claim.submitter
    lang = s.language
    extra = ""
    if claim.status_enum == Status.REJECTED and claim.rejection_reason:
        extra = translate("mail.status.reason", lang, reason=claim.rejection_reason)
    status_label = translate(f"status.{claim.status}", lang)
    mailer.send(
        mailer.Mail(
            to=[s.email],
            subject=translate("mail.status.subject", lang, reference=claim.reference, status=status_label),
            body=translate(
                "mail.status.body",
                lang,
                name=s.name or s.email,
                reference=claim.reference,
                status=status_label,
                extra=extra,
                link=claim_link(claim),
                org=get_settings().organisation_name,
            ),
        )
    )


def task_attachments(claim: Claim) -> list[mailer.MailAttachment]:
    """Bijlagen voor de medewerker: de geparafeerde versie als die er is."""
    result = []
    for att in claim.attachments:
        if att.stamped_path:
            path = storage.absolute(att.stamped_path)
            name = f"paraaf-{Path(att.original_filename).stem}.pdf"
        else:
            path = storage.absolute(att.stored_path)
            name = att.original_filename
        if path.exists():
            result.append(mailer.MailAttachment(path=path, filename=name))
    return result


def approval_link_text(db: Session, claim: Claim, user: User, key: str = "mail.approve_link") -> str:
    """Extra tekst met een goedkeurlink voor een voorzitter die dat aan heeft staan, anders leeg."""
    if claim.status_enum != Status.SUBMITTED or not approval_links.enabled_for(user):
        return ""
    url, expires = approval_links.create(db, claim, user)
    return translate(key, user.language, link=url, until=local_time(expires))


def notify_role(db: Session, claim: Claim) -> None:
    role = ROLE_FOR_STATUS.get(claim.status_enum)
    if role is None:
        return
    for user in users_with_role(db, role):
        lang = user.language
        body = translate(
            "mail.task.body",
            lang,
            name=user.name,
            action=translate(f"task.{role.value}", lang),
            summary=claim_summary(claim, lang),
            link=portal_link(claim),
        )
        mailer.send(
            mailer.Mail(
                to=[user.email],
                subject=translate("mail.task.subject", lang, reference=claim.reference),
                body=body + approval_link_text(db, claim, user),
                attachments=task_attachments(claim),
            )
        )


# ---------------------------------------------------------------- stappen


def create_claim(
    db: Session,
    submitter: Submitter,
    files: list[tuple[str, str, bytes]],
    source: str = "email",
    created_by: User | None = None,
) -> Claim:
    """Maakt een nieuwe declaratie met bijlagen. files = [(bestandsnaam, content_type, data)]."""
    claim = Claim(submitter=submitter, source=source, created_by_id=created_by.id if created_by else None)
    # Onthouden rekeninggegevens alvast invullen (aan te passen door de indiener).
    claim.iban = submitter.iban
    claim.account_holder = submitter.account_holder
    db.add(claim)
    assign_reference(db, claim)
    for filename, ctype, data in files:
        storage.save_attachment(db, claim, filename, ctype, data)
    log_event(db, claim, "created", created_by, note=source)
    db.flush()
    return claim


def complete_details(
    db: Session,
    claim: Claim,
    *,
    iban: str,
    account_holder: str,
    description: str,
    amount_cents: int,
    remember: bool = True,
    user: User | None = None,
    inform: bool = True,
) -> None:
    """De indiener (of een medewerker) vult de gegevens aan; daarna gaat de declaratie naar de voorzitter.

    inform=False: geen statusmelding aan bestuursleden, omdat de declaratie net is aangemaakt en
    de melding over de nieuwe declaratie volgt."""
    if claim.status_enum not in (Status.RECEIVED, Status.SUBMITTED):
        raise WorkflowError("claim_locked")
    claim.iban = normalize_iban(iban)
    claim.account_holder = account_holder.strip()
    claim.description = description.strip()
    claim.amount_cents = amount_cents
    if remember:
        claim.submitter.iban = claim.iban
        claim.submitter.account_holder = claim.account_holder
    first_time = claim.status_enum == Status.RECEIVED
    log_event(db, claim, "details_updated" if not first_time else "submitted", user)
    if first_time:
        set_status(claim, Status.SUBMITTED)
        claim.submitted_at = utcnow()
        db.flush()
        notify_submitter_status(claim)
        notify_role(db, claim)
        if inform:
            notifications.status_changed(db, claim, "submitted", user)


def _require(user: User, role: Role) -> None:
    # Alleen wie de rol zelf heeft mag de stap zetten; beheerder geeft geen extra rechten.
    if not user.has_role(role):
        raise WorkflowError("not_allowed")


def _require_status(claim: Claim, status: Status) -> None:
    if claim.status_enum != status:
        raise WorkflowError("wrong_status")


def approve(db: Session, claim: Claim, user: User, via_link: bool = False) -> None:
    """Voorzitter keurt goed; de bonnen krijgen een paraaf.

    via_link: goedgekeurd met de link uit de mail in plaats van in het portaal (komt in de geschiedenis)."""
    _require(user, Role.CHAIR)
    _require_status(claim, Status.SUBMITTED)
    now = utcnow()
    lang = get_settings().default_language
    lines = stamp_lines(translate("stamp.title", lang), user.name, now.astimezone(_tz()), claim.reference)
    for att in claim.attachments:
        try:
            stamped = stamp_file(storage.absolute(att.stored_path), att.content_type, lines)
            att.stamped_path = str(stamped.relative_to(storage.upload_root().resolve()))
        except Exception:
            log.exception("Paraaf zetten op bijlage %s mislukt", att.id)
    set_status(claim, Status.APPROVED)
    claim.approved_at = now
    claim.approved_by_id = user.id
    log_event(db, claim, "approved", user, note="link" if via_link else "")
    db.flush()
    notify_submitter_status(claim)
    notify_role(db, claim)
    notifications.status_changed(db, claim, "approved", user)


def prepare_payment(db: Session, claim: Claim, user: User) -> None:
    """Boekhouder heeft de betaling klaargezet bij de bank."""
    _require(user, Role.TREASURER)
    _require_status(claim, Status.APPROVED)
    set_status(claim, Status.PAYMENT_PREPARED)
    claim.prepared_at = utcnow()
    claim.prepared_by_id = user.id
    log_event(db, claim, "payment_prepared", user)
    db.flush()
    notify_submitter_status(claim)
    notify_role(db, claim)
    notifications.status_changed(db, claim, "payment_prepared", user)


def mark_paid(db: Session, claim: Claim, user: User) -> None:
    """Secretaris heeft de betaling uitgevoerd bij de bank."""
    _require(user, Role.SECRETARY)
    _require_status(claim, Status.PAYMENT_PREPARED)
    set_status(claim, Status.PAID)
    claim.paid_at = utcnow()
    claim.paid_by_id = user.id
    log_event(db, claim, "paid", user)
    db.flush()
    notify_submitter_status(claim)
    notifications.status_changed(db, claim, "paid", user)


def reject(db: Session, claim: Claim, user: User, reason: str) -> None:
    if not user.is_staff:
        raise WorkflowError("not_allowed")
    if claim.status_enum in (Status.PAID, Status.REJECTED):
        raise WorkflowError("wrong_status")
    set_status(claim, Status.REJECTED)
    claim.rejected_by_id = user.id
    claim.rejection_reason = reason.strip()
    log_event(db, claim, "rejected", user, note=reason.strip())
    db.flush()
    notify_submitter_status(claim)
    notifications.status_changed(db, claim, "rejected", user)


def _status_before_rejection(claim: Claim) -> Status:
    if claim.prepared_at:
        return Status.PAYMENT_PREPARED
    if claim.approved_at:
        return Status.APPROVED
    if claim.submitted_at:
        return Status.SUBMITTED
    return Status.RECEIVED


def undo_info(claim: Claim) -> tuple[str, int | None] | None:
    """Welke stap ongedaan gemaakt kan worden en wie hem zette, of None."""
    status = claim.status_enum
    if status == Status.APPROVED:
        return "approved", claim.approved_by_id
    if status == Status.PAYMENT_PREPARED:
        return "payment_prepared", claim.prepared_by_id
    if status == Status.PAID:
        return "paid", claim.paid_by_id
    if status == Status.REJECTED:
        return "rejected", claim.rejected_by_id
    return None


def can_undo(claim: Claim, user: User) -> bool:
    """Wie de laatste stap zette, of een beheerder, mag hem terugdraaien."""
    info = undo_info(claim)
    if info is None or not user.is_staff:
        return False
    return info[1] == user.id or user.has_role(Role.ADMIN)


def undo(db: Session, claim: Claim, user: User) -> list[str]:
    """Draai de laatste stap terug; de declaratie gaat terug naar de vorige status.

    Geeft de geparafeerde bestanden terug die na de commit weg mogen."""
    info = undo_info(claim)
    if info is None:
        raise WorkflowError("wrong_status")
    if not can_undo(claim, user):
        raise WorkflowError("not_allowed")
    step = info[0]
    stale: list[str] = []
    if step == "approved":
        for att in claim.attachments:
            if att.stamped_path:
                stale.append(att.stamped_path)
                att.stamped_path = None
        claim.approved_at = None
        claim.approved_by_id = None
        set_status(claim, Status.SUBMITTED)
    elif step == "payment_prepared":
        claim.prepared_at = None
        claim.prepared_by_id = None
        set_status(claim, Status.APPROVED)
    elif step == "paid":
        claim.paid_at = None
        claim.paid_by_id = None
        set_status(claim, Status.PAYMENT_PREPARED)
    else:
        claim.rejected_by_id = None
        claim.rejection_reason = ""
        set_status(claim, _status_before_rejection(claim))
    log_event(db, claim, "undone", user, note=step)
    db.flush()
    notify_submitter_status(claim)
    notify_role(db, claim)
    notifications.status_changed(db, claim, "undone", user)
    return stale


def remove_files(paths: list[str]) -> None:
    for rel in paths:
        try:
            storage.absolute(rel).unlink(missing_ok=True)
        except (ValueError, OSError):
            log.warning("Bestand %s niet verwijderd", rel)


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def local_time(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_tz()).strftime("%d-%m-%Y %H:%M")
