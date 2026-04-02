from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.orm import EmailRecord, InboxSession
from app.schemas.sessions import ClassificationPublic, EmailPublic, SessionDetailPublic, SessionPublic

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=list[SessionPublic])
def list_sessions(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    q = (
        select(InboxSession)
        .order_by(InboxSession.updated_at.desc())
        .offset(skip)
        .limit(min(limit, 200))
    )
    rows = db.scalars(q).all()
    return [SessionPublic.model_validate(r) for r in rows]


@router.get("/{session_id}", response_model=SessionDetailPublic)
def get_session(session_id: int, db: Session = Depends(get_db)):
    row = db.scalars(
        select(InboxSession)
        .where(InboxSession.id == session_id)
        .options(
            selectinload(InboxSession.emails).selectinload(EmailRecord.classification),
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    def _ek(e: EmailRecord):
        if e.received_at:
            return (0, e.received_at.timestamp(), e.id)
        return (1, 0.0, e.id)

    emails = sorted(row.emails, key=_ek)
    return SessionDetailPublic(
        id=row.id,
        gmail_thread_id=row.gmail_thread_id,
        latest_category=row.latest_category,
        created_at=row.created_at,
        updated_at=row.updated_at,
        emails=[
            EmailPublic(
                id=e.id,
                gmail_message_id=e.gmail_message_id,
                from_address=e.from_address,
                subject=e.subject,
                body_text=e.body_text,
                received_at=e.received_at,
                reply_sent_at=e.reply_sent_at,
                reply_skipped_reason=e.reply_skipped_reason,
                outbound_gmail_message_id=e.outbound_gmail_message_id,
                last_error=e.last_error,
                classification=(
                    ClassificationPublic.model_validate(e.classification)
                    if e.classification
                    else None
                ),
            )
            for e in emails
        ],
    )
