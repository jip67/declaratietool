"""Uitgaande e-mail via SMTP. Zonder SMTP-server worden berichten alleen gelogd."""

import logging
import mimetypes
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

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


def build_message(mail: Mail) -> EmailMessage:
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((settings.app_name, settings.mail_from))
    msg["To"] = ", ".join(mail.to)
    msg["Subject"] = mail.subject
    msg["Message-ID"] = make_msgid(domain=settings.mail_from.split("@")[-1])
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
    settings = get_settings()
    msg = build_message(mail)
    outbox.append(msg)
    if not settings.smtp_host:
        log.info("SMTP niet ingesteld; mail aan %s niet verstuurd: %s\n%s", recipients, mail.subject, mail.body)
        return
    try:
        if settings.smtp_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        with server:
            if settings.smtp_starttls and not settings.smtp_ssl:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception:  # mailfouten mogen de workflow niet blokkeren
        log.exception("Versturen van mail aan %s mislukt", recipients)
