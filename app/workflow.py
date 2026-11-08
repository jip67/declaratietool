"""De stappen van een declaratie en de berichten die daarbij horen.

ontvangen -> (indiener vult aan) -> ingediend -> (voorzitter keurt goed + paraaf)
-> goedgekeurd -> (boekhouder zet betaling klaar) -> klaargezet
-> (secretaris voert betaling uit bij de bank) -> betaald

Bij elke stap krijgt de indiener een update en krijgt wie daarna aan zet is een bericht.
"""

import base64
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import approval_links, mailer, notifications, storage
from .config import get_settings
from .i18n import translate
from .models import ROLE_FOR_STATUS, Attachment, Claim, Event, Role, Status, Submitter, User, utcnow
from .security import format_iban, normalize_iban
from .stamping import SignatureError, normalize_signature, preview_path, stamp_file, stamp_lines

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


TEST_PREFIX = "TEST-"


def assign_reference(db: Session, claim: Claim) -> None:
    """Kenmerk zoals D2026-0001; een testdeclaratie telt apart (TEST-D2026-0001) en kost geen echt nummer."""
    db.flush()
    year = utcnow().year
    prefix = f"{TEST_PREFIX if claim.is_test else ''}{get_settings().reference_prefix}{year}-"
    count = db.scalar(select(func.count(Claim.id)).where(Claim.reference.like(prefix + "%"))) or 0
    claim.reference = f"{prefix}{count + 1:04d}"


def users_with_role(db: Session, role: Role) -> list[User]:
    users = db.scalars(select(User).where(User.active.is_(True))).all()
    return [u for u in users if u.has_role(role)]


def role_holders(db: Session, claim: Claim, role: Role) -> list[User]:
    """Wie bij deze declaratie de stap van deze rol zet; bij een testdeclaratie alleen de beheerder die hem maakte."""
    if claim.is_test:
        owner = db.get(User, claim.test_user_id)
        return [owner] if owner is not None and owner.active else []
    return users_with_role(db, role)


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


# Deze statussen krijgt de indiener altijd per mail; de tussenstappen alleen als hij dat aanzette.
ALWAYS_TELL_SUBMITTER = (Status.PAID, Status.REJECTED)


def notify_submitter_status(claim: Claim, always: bool = False) -> None:
    """Statusmail aan de indiener. always: ook bij een tussenstap als hij die niet wil."""
    s = claim.submitter
    if not (always or s.status_updates or claim.status_enum in ALWAYS_TELL_SUBMITTER):
        return
    lang = s.language
    extra = ""
    if claim.status_enum == Status.REJECTED and claim.rejection_reason:
        extra = translate("mail.status.reason", lang, reason=claim.rejection_reason)
    status_label = status_text(claim, lang)
    if claim.status_enum == Status.PAID:
        extra = payment_note(claim, lang) + "\n"
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
    if claim.status_enum != Status.SUBMITTED or not approval_links.enabled_for(user, claim):
        return ""
    url, expires = approval_links.create(db, claim, user)
    return translate(key, user.language, link=url, until=local_time(expires))


def notify_role(db: Session, claim: Claim) -> None:
    role = ROLE_FOR_STATUS.get(claim.status_enum)
    if role is None:
        return
    for user in role_holders(db, claim, role):
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
    test_user: User | None = None,
) -> Claim:
    """Maakt een nieuwe declaratie met bijlagen. files = [(bestandsnaam, content_type, data)].

    test_user: maak een testdeclaratie waarin deze beheerder alle rollen speelt (zie create_test_claim)."""
    claim = Claim(submitter=submitter, source=source, created_by_id=created_by.id if created_by else None,
                  test_user_id=test_user.id if test_user else None)
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


def can_test(user: User) -> bool:
    return user.active and user.has_role(Role.ADMIN)


def sample_receipt(lang: str) -> tuple[str, str, bytes]:
    """Een voorbeeldbon (pdf) voor een testdeclaratie zonder eigen bijlage."""
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, height - 100, translate("test.receipt.title", lang))
    c.setFont("Helvetica", 12)
    for i, line in enumerate(translate("test.receipt.body", lang).split("\n")):
        c.drawString(72, height - 140 - i * 18, line)
    c.save()
    return translate("test.receipt.filename", lang), "application/pdf", buf.getvalue()


def create_test_claim(db: Session, admin: User, files: list[tuple[str, str, bytes]], source: str = "portal") -> Claim:
    """Testdeclaratie: de beheerder is indiener, voorzitter, boekhouder en secretaris tegelijk.

    Alleen hij ziet de declaratie en krijgt er mail over; de andere bestuursleden merken er niets van
    (geen taken, herinneringen, meldingen of teller op het app-icoon). Zonder bijlage komt er een voorbeeldbon bij."""
    if not can_test(admin):
        raise WorkflowError("not_allowed")
    submitter = get_or_create_submitter(db, admin.email, admin.name, language=admin.language)
    claim = create_claim(db, submitter, files or [sample_receipt(admin.language)], source=source,
                         created_by=admin if source == "portal" else None, test_user=admin)
    log_event(db, claim, "test_created", admin)
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


def _require(claim: Claim, user: User, role: Role) -> None:
    # Alleen wie de rol zelf heeft mag de stap zetten; beheerder geeft geen extra rechten.
    # Uitzondering: bij een testdeclaratie speelt de beheerder die hem maakte alle rollen.
    if not claim.acts_as(user, role):
        raise WorkflowError("not_allowed")


def _require_status(claim: Claim, status: Status) -> None:
    if claim.status_enum != status:
        raise WorkflowError("wrong_status")


def parse_signature(value: str) -> bytes:
    """Lees de getekende paraaf uit het formulier (een data-url met een PNG) en maak hem netjes.

    Gooit WorkflowError('signature_required') als er niets getekend is."""
    value = (value or "").strip()
    prefix = "data:image/png;base64,"
    if not value.startswith(prefix):
        raise WorkflowError("signature_required")
    try:
        data = base64.b64decode(value[len(prefix):], validate=True)
        return normalize_signature(data)
    except (ValueError, SignatureError) as exc:
        raise WorkflowError("signature_required") from exc


def stamp_attachment(claim: Claim, att: Attachment, name: str, when: datetime, signature: bytes | None = None) -> None:
    """Zet de paraaf van de voorzitter op een bijlage; een mislukte paraaf houdt de declaratie niet op.

    signature: de getekende paraaf (PNG); zonder komt er een tekststempel op."""
    lang = get_settings().default_language
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    lines = stamp_lines(translate("stamp.title", lang), name, when.astimezone(_tz()), claim.reference)
    try:
        stamped = stamp_file(storage.absolute(att.stored_path), att.content_type, lines, signature)
        att.stamped_path = str(stamped.relative_to(storage.upload_root().resolve()))
    except Exception:
        log.exception("Paraaf zetten op bijlage %s mislukt", att.id)


def approve(db: Session, claim: Claim, user: User, via_link: bool = False,
            signature: bytes | None = None, remember_signature: bool = False) -> None:
    """Voorzitter keurt goed; de bonnen krijgen zijn getekende paraaf.

    via_link: goedgekeurd met de link uit de mail in plaats van in het portaal (komt in de geschiedenis).
    signature: de getekende paraaf (zie parse_signature); de routes eisen die, zonder komt er een stempel.
    remember_signature: bewaar de paraaf bij de gebruiker voor de volgende keer; zo niet, dan vergeten we een eerder bewaarde."""
    _require(claim, user, Role.CHAIR)
    _require_status(claim, Status.SUBMITTED)
    now = utcnow()
    claim.approval_signature = signature
    if signature:
        user.signature = signature if remember_signature else None
    for att in claim.attachments:
        stamp_attachment(claim, att, user.name, now, signature)
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
    _require(claim, user, Role.TREASURER)
    _require_status(claim, Status.APPROVED)
    set_status(claim, Status.PAYMENT_PREPARED)
    claim.prepared_at = utcnow()
    claim.prepared_by_id = user.id
    log_event(db, claim, "payment_prepared", user)
    db.flush()
    notify_submitter_status(claim)
    notify_role(db, claim)
    notifications.status_changed(db, claim, "payment_prepared", user)


# Hoe ver de betaaldatum van vandaag af mag liggen: een vergeten klik achteraf, of een betaling ver vooruit ingepland.
PAYMENT_DATE_PAST_DAYS = 90
PAYMENT_DATE_FUTURE_DAYS = 365


def local_today() -> date:
    return datetime.now(_tz()).date()


def payment_date_bounds() -> tuple[date, date, date]:
    """Vroegste, standaard (vandaag) en laatste betaaldatum die het formulier toestaat."""
    today = local_today()
    return today - timedelta(days=PAYMENT_DATE_PAST_DAYS), today, today + timedelta(days=PAYMENT_DATE_FUTURE_DAYS)


def parse_payment_date(value: str) -> date:
    """De datum uit het formulier (jjjj-mm-dd); leeg is vandaag."""
    value = (value or "").strip()
    if not value:
        return local_today()
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise WorkflowError("payment_date_invalid") from None
    first, _, last = payment_date_bounds()
    if not first <= result <= last:
        raise WorkflowError("payment_date_range")
    return result


def mark_paid(db: Session, claim: Claim, user: User, payment_date: date | None = None) -> None:
    """Secretaris heeft de betaling uitgevoerd of ingepland bij de bank (payment_date, standaard vandaag)."""
    _require(claim, user, Role.SECRETARY)
    _require_status(claim, Status.PAYMENT_PREPARED)
    set_status(claim, Status.PAID)
    claim.paid_at = utcnow()
    claim.paid_by_id = user.id
    claim.payment_date = payment_date or local_today()
    log_event(db, claim, "paid", user, note=claim.payment_date.isoformat())
    db.flush()
    notify_submitter_status(claim)
    notifications.status_changed(db, claim, "paid", user)


def reject(db: Session, claim: Claim, user: User, reason: str) -> None:
    if not user.is_staff or not claim.visible_to(user):
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
    if info is None or not user.is_staff or not claim.visible_to(user):
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
        claim.approval_signature = None
        claim.approved_by_id = None
        set_status(claim, Status.SUBMITTED)
    elif step == "payment_prepared":
        claim.prepared_at = None
        claim.prepared_by_id = None
        set_status(claim, Status.APPROVED)
    elif step == "paid":
        claim.paid_at = None
        claim.paid_by_id = None
        claim.payment_date = None
        set_status(claim, Status.PAYMENT_PREPARED)
    else:
        claim.rejected_by_id = None
        claim.rejection_reason = ""
        set_status(claim, _status_before_rejection(claim))
    log_event(db, claim, "undone", user, note=step)
    db.flush()
    # Kreeg de indiener "betaald" of "afgewezen", dan moet hij ook horen dat dat is teruggedraaid.
    notify_submitter_status(claim, always=step in ("paid", "rejected"))
    notify_role(db, claim)
    notifications.status_changed(db, claim, "undone", user)
    return stale


def replace_attachment(db: Session, claim: Claim, att: Attachment, filename: str, content_type: str,
                       data: bytes, user: User) -> list[str]:
    """Vervang het bestand van een bijlage, bijvoorbeeld door een met de hand getekende versie.

    Was de declaratie al goedgekeurd, dan krijgt het nieuwe bestand dezelfde paraaf
    (de getekende paraaf, naam en tijdstip van de oorspronkelijke goedkeuring). Geeft de oude bestanden
    terug die na de commit weg mogen."""
    stale = [p for p in (att.stored_path, att.stamped_path) if p]
    old_name = att.original_filename
    att.stored_path = storage.write_file(claim, content_type, data)
    att.original_filename = storage.safe_filename(filename)
    att.content_type = content_type
    att.size = len(data)
    att.stamped_path = None
    if claim.approved_at is not None:
        approver = db.get(User, claim.approved_by_id) if claim.approved_by_id else None
        stamp_attachment(claim, att, approver.name if approver else "", claim.approved_at, claim.approval_signature)
    log_event(db, claim, "attachment_replaced", user, note=f"{old_name} → {att.original_filename}")
    return stale


def change_submitter(db: Session, claim: Claim, email: str) -> None:
    """Koppel de declaratie aan een ander e-mailadres, bijvoorbeeld na een typefout.

    Het oude adres wordt vergeten als er verder geen declaraties aan hangen."""
    old = claim.submitter
    new = get_or_create_submitter(db, email, old.name, language=old.language)
    if new is old:
        return
    if not new.iban and not new.account_holder:
        new.iban, new.account_holder = old.iban, old.account_holder
    claim.submitter = new
    db.flush()
    if not db.scalar(select(func.count(Claim.id)).where(Claim.submitter_id == old.id)):
        db.delete(old)


def remove_files(paths: list[str]) -> None:
    for rel in paths:
        try:
            path = storage.absolute(rel)
            path.unlink(missing_ok=True)
            if path.name.endswith("-paraaf.pdf"):
                preview_path(path).unlink(missing_ok=True)
        except (ValueError, OSError):
            log.warning("Bestand %s niet verwijderd", rel)


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def effective_payment_date(claim: Claim) -> date | None:
    """De betaaldatum; bij declaraties van voor dit veld de dag waarop op 'betaald' werd geklikt."""
    if claim.payment_date:
        return claim.payment_date
    if claim.paid_at:
        value = claim.paid_at if claim.paid_at.tzinfo else claim.paid_at.replace(tzinfo=UTC)
        return value.astimezone(_tz()).date()
    return None


def payment_scheduled(claim: Claim) -> bool:
    """Betaald, maar met een datum in de toekomst: de betaling staat ingepland bij de bank."""
    when = effective_payment_date(claim)
    return claim.status_enum == Status.PAID and when is not None and when > local_today()


def long_date(value: date, lang: str | None = None) -> str:
    """Bijvoorbeeld '10 november 2026' (of 'November 10, 2026' in het Engels, volgens de vertaling)."""
    months = translate("date.months", lang).split(",")
    month = months[value.month - 1] if len(months) == 12 else str(value.month)
    return translate("date.long", lang, day=value.day, month=month, year=value.year)


def long_date_text(value: str, lang: str | None = None) -> str:
    """long_date voor een datum als tekst (jjjj-mm-dd), zoals in de geschiedenis; anders de tekst zelf."""
    try:
        return long_date(date.fromisoformat(value), lang)
    except (TypeError, ValueError):
        return value or ""


def payment_note(claim: Claim, lang: str | None = None) -> str:
    """'Betaling ingepland op 10 november 2026' of 'Betaald op 8 november 2026'; leeg als nog niet betaald."""
    when = effective_payment_date(claim)
    if claim.status_enum != Status.PAID or when is None:
        return ""
    key = "payment.scheduled_on" if payment_scheduled(claim) else "payment.paid_on"
    return translate(key, lang, date=long_date(when, lang))


def status_text(claim: Claim, lang: str | None = None) -> str:
    """De status zoals de indiener hem ziet: bij een ingeplande betaling 'Betaling ingepland'."""
    if payment_scheduled(claim):
        return translate("status.paid_scheduled", lang)
    return translate(f"status.{claim.status}", lang)


def local_time(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_tz()).strftime("%d-%m-%Y %H:%M")
