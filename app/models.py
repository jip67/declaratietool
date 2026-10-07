"""Datamodel van de declaratietool."""

import enum
import secrets
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    return secrets.token_urlsafe(24)


class Role(str, enum.Enum):
    CHAIR = "chair"  # voorzitter: keurt goed en parafeert
    TREASURER = "treasurer"  # boekhouder/penningmeester: zet betaling klaar
    SECRETARY = "secretary"  # secretaris: geeft betaling akkoord bij de bank
    ADMIN = "admin"  # beheert gebruikers


class Status(str, enum.Enum):
    RECEIVED = "received"  # bon ontvangen, wacht op gegevens van indiener
    SUBMITTED = "submitted"  # compleet, wacht op goedkeuring voorzitter
    APPROVED = "approved"  # goedgekeurd, wacht op klaarzetten betaling
    PAYMENT_PREPARED = "payment_prepared"  # klaargezet, wacht op akkoord secretaris
    PAID = "paid"  # betaald
    REJECTED = "rejected"  # afgewezen


# Welke rol aan zet is in welke status (None = de indiener of niemand).
ROLE_FOR_STATUS: dict[Status, Role] = {
    Status.SUBMITTED: Role.CHAIR,
    Status.APPROVED: Role.TREASURER,
    Status.PAYMENT_PREPARED: Role.SECRETARY,
}

OPEN_STATUSES = (Status.RECEIVED, Status.SUBMITTED, Status.APPROVED, Status.PAYMENT_PREPARED)


class User(Base):
    """Een medewerker die kan inloggen op het portaal."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    roles: Mapped[str] = mapped_column(String(255), default="")  # komma-gescheiden
    language: Mapped[str] = mapped_column(String(8), default="nl")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def role_list(self) -> list[Role]:
        return [Role(r) for r in self.roles.split(",") if r]

    def has_role(self, role: Role) -> bool:
        return role in self.role_list


class Submitter(Base):
    """Iemand die declaraties indient. Rekeninggegevens worden onthouden."""

    __tablename__ = "submitters"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    iban: Mapped[str] = mapped_column(String(64), default="")
    account_holder: Mapped[str] = mapped_column(String(255), default="")
    language: Mapped[str] = mapped_column(String(8), default="nl")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    claims: Mapped[list["Claim"]] = relationship(back_populates="submitter")


class Claim(Base):
    """Een declaratie."""

    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, default="")
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=new_token)
    submitter_id: Mapped[int] = mapped_column(ForeignKey("submitters.id"))
    status: Mapped[str] = mapped_column(String(32), default=Status.RECEIVED.value, index=True)
    source: Mapped[str] = mapped_column(String(16), default="email")  # email | portal

    description: Mapped[str] = mapped_column(Text, default="")
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iban: Mapped[str] = mapped_column(String(64), default="")
    account_holder: Mapped[str] = mapped_column(String(255), default="")

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    prepared_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    paid_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    submitter: Mapped[Submitter] = relationship(back_populates="claims")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="Attachment.id"
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="Event.id"
    )
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])

    @property
    def status_enum(self) -> Status:
        return Status(self.status)

    @property
    def is_complete(self) -> bool:
        return bool(self.description and self.iban and self.account_holder and self.amount_cents)

    @property
    def amount_display(self) -> str:
        if self.amount_cents is None:
            return "-"
        euros, cents = divmod(self.amount_cents, 100)
        return f"€ {euros:,}".replace(",", ".") + f",{cents:02d}"


class Attachment(Base):
    """Een bon of factuur (foto of pdf) bij een declaratie."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(Integer, default=0)
    stamped_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="attachments")


class Event(Base):
    """Logboek: wie deed wat en wanneer."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")

    claim: Mapped[Claim] = relationship(back_populates="events")
    user: Mapped[User | None] = relationship()


class KeyValue(Base):
    """Kleine sleutel/waarde-opslag, bijvoorbeeld voor de datum van de laatste herinneringsronde."""

    __tablename__ = "key_values"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
