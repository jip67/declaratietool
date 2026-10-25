"""Goedkeuren via een link in de mail, zonder inloggen (alleen voor de voorzitter, per gebruiker aan te zetten).

Zo blijft het veilig genoeg:
- de link bevat een lang willekeurig token; in de database staat alleen de sha256-hash ervan;
- de link hoort bij één declaratie en één voorzitter en verloopt na APPROVAL_LINK_DAYS dagen;
- de link werkt één keer, en alleen zolang de declaratie in de status staat waarin hij is verstuurd
  (na goedkeuren, afwijzen of ongedaan maken is hij dus ongeldig);
- openen (GET) verandert niets; pas de knop op de pagina (POST) keurt goed, zodat een virusscanner
  die links in mail opent niet per ongeluk goedkeurt;
- de goedkeuring komt in de geschiedenis van de declaratie, met 'via link' en het IP-adres.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ApprovalLink, Claim, Role, Status, User, utcnow


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def enabled_for(user: User) -> bool:
    return user.approve_by_link and user.active and user.has_role(Role.CHAIR)


def create(db: Session, claim: Claim, user: User) -> tuple[str, datetime]:
    """Maak een nieuwe link; geeft de url en de vervaldatum terug."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    expires = now + timedelta(days=get_settings().approval_link_days)
    db.add(ApprovalLink(token_hash=_hash(token), claim_id=claim.id, user_id=user.id, created_at=now, expires_at=expires))
    db.flush()
    return f"{get_settings().base_url}/a/{token}", expires


def find(db: Session, token: str) -> ApprovalLink | None:
    if not token or len(token) > 128:
        return None
    return db.scalar(select(ApprovalLink).where(ApprovalLink.token_hash == _hash(token)))


def problem(link: ApprovalLink) -> str | None:
    """Waarom de link niet (meer) gebruikt kan worden, of None als hij geldig is."""
    claim, user = link.claim, link.user
    if link.used_at is not None:
        return "used"
    if claim.status_enum != Status.SUBMITTED or _aware(link.created_at) < _aware(claim.status_changed_at):
        return "handled"
    if utcnow() > _aware(link.expires_at):
        return "expired"
    if user is None or not enabled_for(user):
        return "disabled"
    return None


def fingerprint(claim: Claim) -> str:
    """Verandert als de gegevens wijzigen terwijl de pagina openstaat; dan eerst opnieuw laten bekijken."""
    parts = [str(claim.amount_cents), claim.iban, claim.account_holder, claim.description]
    parts += [f"{a.id}:{a.stored_path}" for a in claim.attachments]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:32]
