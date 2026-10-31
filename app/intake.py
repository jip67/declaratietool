"""Inkomende mail ophalen (IMAP) en omzetten in declaraties."""

import email
import logging
import re
from email.message import Message
from email.policy import default as default_policy
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import activity, mailconfig, mailer, notifications, workflow
from .config import get_settings
from .i18n import pick_language, translate
from .models import Claim
from .storage import guess_type

log = logging.getLogger(__name__)

# Kleine inline-afbeeldingen zijn meestal logo's in een handtekening.
MIN_INLINE_IMAGE_BYTES = 30_000
# Antwoorden en doorgestuurde mails (Nederlands, Engels, Duits, Frans).
REPLY_PREFIX = re.compile(r"^\s*((re|aw|antw|sv|fw|fwd|wg|tr|doorgestuurd)\s*:\s*)+", re.IGNORECASE)


def extract_files(msg: Message) -> list[tuple[str, str, bytes]]:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    files = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename() or ""
        ctype = guess_type(filename, part.get_content_type())
        if ctype is None:
            continue
        data = part.get_payload(decode=True) or b""
        if not data or len(data) > max_bytes:
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if disposition != "attachment" and ctype.startswith("image/") and len(data) < MIN_INLINE_IMAGE_BYTES:
            continue
        files.append((filename or f"bijlage{len(files) + 1}", ctype, data))
    return files


def replied_claim(db: Session, msg: Message) -> Claim | None:
    """De declaratie waar deze mail een antwoord op is (of een doorgestuurde mail van), of None.

    Herkend aan het kenmerk van een bestaande declaratie in een onderwerp dat begint met Re:,
    Fwd: en dergelijke. Zo wordt een bedankje met een logo in de handtekening geen nieuwe
    declaratie, die de indiener daarna dagen achter elkaar om gegevens vraagt.
    """
    subject = " ".join(str(msg.get("Subject") or "").split())
    if not REPLY_PREFIX.match(subject):
        return None
    prefix = re.escape(get_settings().reference_prefix)
    for reference in re.findall(rf"\b{prefix}\d{{4}}-\d{{3,}}\b", subject):
        claim = db.scalar(select(Claim).where(Claim.reference == reference))
        if claim is not None:
            return claim
    return None


def is_automatic(msg: Message) -> bool:
    auto = (msg.get("Auto-Submitted") or "no").lower()
    precedence = (msg.get("Precedence") or "").lower()
    return auto != "no" or precedence in ("bulk", "junk", "auto_reply") or bool(msg.get("X-Autoreply"))


def parse(raw: bytes) -> Message:
    return email.message_from_bytes(raw, policy=default_policy)


def sender_and_subject(msg: Message) -> tuple[str, str]:
    """Afzender en onderwerp voor het logboek; vangt kapotte kopregels af."""
    try:
        sender = str(msg.get("From", "") or "")
        subject = str(msg.get("Subject", "") or "")
    except Exception:
        return "", ""
    return sender.strip(), " ".join(subject.split())


def process_message(db: Session, raw: bytes) -> str:
    """Verwerkt één mail en legt hem vast in het logboek. Geeft terug wat er gebeurde."""
    msg = parse(raw)
    files = extract_files(msg)
    result, claim = _process(db, msg, files)
    sender, subject = sender_and_subject(msg)
    try:
        activity.record_mail(db, sender, subject, len(files), result, claim)
    except Exception:
        # De declaratie is al opgeslagen; een mislukte logregel mag niet tot een dubbele leiden.
        db.rollback()
        log.exception("Mail kon niet in het logboek worden gezet")
    notifications.incoming_mail(db, sender, subject, len(files), result, claim)
    return result


def _process(db: Session, msg: Message, files: list[tuple[str, str, bytes]]):
    name, address = parseaddr(msg.get("From", ""))
    address = address.strip().lower()
    settings = get_settings()
    if not address or "@" not in address:
        return "ignored:no_sender", None
    if address == mailconfig.load(db).mail_from.lower() or is_automatic(msg):
        return "ignored:automatic", None

    lang = pick_language(accept_language=msg.get("Content-Language"))
    replied = replied_claim(db, msg)
    if replied is not None:
        if files:
            # Misschien bedoeld als nieuwe bon: laat weten dat dat via een nieuwe mail moet.
            mailer.send(
                mailer.Mail(
                    to=[address],
                    subject=translate("mail.reply_ignored.subject", lang, reference=replied.reference),
                    body=translate("mail.reply_ignored.body", lang, reference=replied.reference,
                                   org=settings.organisation_name),
                )
            )
        return "ignored:reply", replied
    if not files:
        mailer.send(
            mailer.Mail(
                to=[address],
                subject=translate("mail.no_attachment.subject", lang),
                body=translate("mail.no_attachment.body", lang, org=settings.organisation_name),
            )
        )
        return "rejected:no_attachment", None

    submitter = workflow.get_or_create_submitter(db, address, name, lang)
    claim = workflow.create_claim(db, submitter, files, source="email")
    subject = (msg.get("Subject") or "").strip()
    if subject and not claim.description:
        claim.description = subject[:500]
    db.commit()
    workflow.notify_received(claim)
    notifications.new_claim(db, claim)
    log.info("Declaratie %s aangemaakt vanuit mail van %s", claim.reference, address)
    return f"created:{claim.reference}", claim


def poll_mailbox(session_factory) -> int:
    """Haalt ongelezen mail op. Geeft het aantal verwerkte berichten terug."""
    config = mailconfig.load()
    if not config.imap_host:
        return 0
    processed = 0
    with mailconfig.imap_connect(config) as imap:
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return 0
        for num in data[0].split():
            status, parts = imap.fetch(num, "(RFC822)")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            db = session_factory()
            try:
                result = process_message(db, parts[0][1])
                log.info("Mail %s: %s", num.decode(), result)
                processed += 1
            except Exception:
                db.rollback()
                log.exception("Verwerken van mail %s mislukt", num)
                _record_failure(db, parts[0][1])
                # Markeer als ongelezen zodat het later opnieuw geprobeerd wordt.
                imap.store(num, "-FLAGS", "\\Seen")
            finally:
                db.close()
    return processed


def _record_failure(db: Session, raw: bytes) -> None:
    """Legt een mislukte mail één keer per dag vast; hij wordt elke ronde opnieuw geprobeerd."""
    try:
        sender, subject = sender_and_subject(parse(raw))
        if not activity.recent_error(db, sender, subject):
            activity.record_mail(db, sender, subject, 0, "error")
            notifications.incoming_mail(db, sender, subject, 0, "error")
    except Exception:
        db.rollback()
        log.exception("Mail kon niet in het logboek worden gezet")
