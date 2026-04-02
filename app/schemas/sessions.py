from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClassificationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    missing_rfq_fields: list[str] | None
    created_at: datetime | None


class EmailPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gmail_message_id: str
    from_address: str
    subject: str
    body_text: str
    received_at: datetime | None
    reply_sent_at: datetime | None
    reply_skipped_reason: str | None
    outbound_gmail_message_id: str | None
    last_error: str | None
    classification: ClassificationPublic | None


class SessionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gmail_thread_id: str
    latest_category: str | None
    created_at: datetime
    updated_at: datetime


class SessionDetailPublic(SessionPublic):
    emails: list[EmailPublic]
