"""Uitgaande e-mail via SMTP. Zonder SMTP-server worden berichten alleen gelogd."""

import logging
import mimetypes
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from . import mailconfig
from .config import get_settings

log = logging.getLogger(__name__)

# In tests vangen we verzonden mails hier op.
outbox: list[EmailMessage] = []


@dataclass
class MailAttachment:
    path: Path
    filename: str
    content_type: str | None = None


@dataclass
class Mail:
    to: list[str]
    subject: str
    body: str
    attachments: list[MailAttachment] = field(default_factory=list)


def build_message(mail: Mail, config: mailconfig.MailConfig | None = None) -> EmailMessage:
    settings = get_settings()
    config = config or mailconfig.load()
    msg = EmailMessage()
    msg["From"] = formataddr((config.mail_from_name or settings.app_name, config.mail_from))
    msg["To"] = ", ".join(mail.to)
    msg["Subject"] = mail.subject
    msg["Message-ID"] = make_msgid(domain=config.mail_from.split("@")[-1])
    # Voorkomt dat auto-replies van ontvangers als nieuwe declaratie binnenkomen.
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(mail.body)
    for att in mail.attachments:
        ctype = att.content_type or mimetypes.guess_type(att.filename)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(att.path.read_bytes(), maintype=maintype, subtype=subtype, filename=att.filename)
    return msg


def send(mail: Mail) -> None:
    recipients = [r for r in mail.to if r]
    if not recipients:
        return
    mail.to = recipients
    config = mailconfig.load()
    msg = build_message(mail, config)
    outbox.append(msg)
    if not config.smtp_host:
        log.info("SMTP niet ingesteld; mail aan %s niet verstuurd: %s\n%s", recipients, mail.subject, mail.body)
        return
    try:
        with mailconfig.smtp_connect(config) as server:
            server.send_message(msg)
    except Exception:  # mailfouten mogen de workflow niet blokkeren
        log.exception("Versturen van mail aan %s mislukt", recipients)
