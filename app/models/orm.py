from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InboxSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    latest_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    emails: Mapped[list["EmailRecord"]] = relationship("EmailRecord", back_populates="session")


class EmailRecord(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    from_address: Mapped[str] = mapped_column(String(512), default="")
    subject: Mapped[str] = mapped_column(String(1024), default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_skipped_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    outbound_gmail_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    session: Mapped["InboxSession"] = relationship("InboxSession", back_populates="emails")
    classification: Mapped["ClassificationRecord | None"] = relationship(
        "ClassificationRecord", back_populates="email", uselist=False
    )


class ClassificationRecord(Base):
    __tablename__ = "classifications"
    __table_args__ = (UniqueConstraint("email_id", name="uq_classification_email"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    missing_rfq_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    email: Mapped["EmailRecord"] = relationship("EmailRecord", back_populates="classification")
