"""Inbox processing pipeline (used by Dramatiq actors)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.classification import ClassificationOutput, classify_email_text
from app.agents.reply import draft_reply
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.categories import CATEGORY_TO_GMAIL_LABEL, gmail_label_for_category
from app.integrations.gmail import GmailClient
from app.integrations.gmail.client import parse_message_resource
from app.models.orm import ClassificationRecord, EmailRecord, InboxSession

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enqueue_draft(email_id: int) -> None:
    from app.workers.tasks import draft_and_send_reply

    draft_and_send_reply.send(email_id)


def _thread_context_for_db(db: Session, session_id: int, before_email_id: int | None) -> str:
    q = (
        select(EmailRecord)
        .where(EmailRecord.session_id == session_id)
        .options(selectinload(EmailRecord.classification))
        .order_by(EmailRecord.received_at.asc().nullsfirst(), EmailRecord.id.asc())
    )
    rows = db.scalars(q).all()
    parts: list[str] = []
    for e in rows:
        if before_email_id is not None and e.id == before_email_id:
            break
        cat = e.classification.category if e.classification else "unknown"
        parts.append(
            f"[From: {e.from_address}] [Class: {cat}] Subject: {e.subject}\n{e.body_text[:4000]}"
        )
    return "\n\n---\n\n".join(parts)


def _normalize_classification(raw: ClassificationOutput) -> ClassificationOutput:
    cat = raw.category.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "quote_request": "rfq",
        "rate_request": "rfq",
        "quotation": "rfq",
        "booking": "booking_request",
        "track": "tracking_inquiry",
        "tracking": "tracking_inquiry",
        "docs": "documentation",
        "documents": "documentation",
        "general": "general_inquiry",
        "spam": "not_relevant",
    }
    cat = aliases.get(cat, cat)
    if cat not in CATEGORY_TO_GMAIL_LABEL:
        raise ValueError(f"Invalid category from model: {raw.category!r}")
    mf = [x.strip().lower().replace(" ", "_") for x in raw.missing_fields]
    allowed = {"origin", "destination", "cargo_type", "weight", "dates"}
    mf = [x for x in mf if x in allowed]
    return ClassificationOutput(category=cat, missing_fields=mf)


def run_classify_inbound(gmail_message_id: str) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        gmail = GmailClient(settings)
        existing = db.scalar(
            select(EmailRecord)
            .where(EmailRecord.gmail_message_id == gmail_message_id)
            .options(selectinload(EmailRecord.classification))
        )
        if existing and existing.classification:
            if existing.reply_sent_at or existing.reply_skipped_reason:
                return
            _enqueue_draft(existing.id)
            db.commit()
            return

        raw_msg = gmail.get_message(gmail_message_id)
        parsed = parse_message_resource(raw_msg)
        thread_id = parsed["thread_id"]

        session = db.scalar(select(InboxSession).where(InboxSession.gmail_thread_id == thread_id))
        if not session:
            session = InboxSession(gmail_thread_id=thread_id)
            db.add(session)
            db.flush()

        email = existing
        if not email:
            email = EmailRecord(
                session_id=session.id,
                gmail_message_id=parsed["gmail_message_id"],
                thread_id=thread_id,
                from_address=parsed["from_address"],
                subject=parsed["subject"],
                body_text=parsed["body_text"] or parsed["snippet"],
                received_at=parsed["received_at"] or _utcnow(),
            )
            db.add(email)
            db.flush()
        else:
            email.from_address = parsed["from_address"] or email.from_address
            email.subject = parsed["subject"] or email.subject
            email.body_text = parsed["body_text"] or email.body_text or parsed["snippet"]

        if email.classification:
            if email.reply_sent_at or email.reply_skipped_reason:
                db.commit()
                return
            _enqueue_draft(email.id)
            db.commit()
            return

        ctx = _thread_context_for_db(db, session.id, before_email_id=email.id)
        current = f"From: {email.from_address}\nSubject: {email.subject}\n\n{email.body_text}"
        raw_out = classify_email_text(thread_context=ctx, current_email=current, settings=settings)
        normalized = _normalize_classification(raw_out)

        clf = ClassificationRecord(
            email_id=email.id,
            category=normalized.category,
            missing_rfq_fields=normalized.missing_fields if normalized.category == "rfq" else [],
            model_raw=raw_out.model_dump_json(),
        )
        db.add(clf)
        session.latest_category = normalized.category
        email.last_error = None
        db.flush()

        label_name = gmail_label_for_category(normalized.category)
        try:
            gmail.add_labels(gmail_message_id, [label_name])
        except Exception as ex:
            email.last_error = f"label: {ex}"
            logger.exception("Gmail label failed for %s", gmail_message_id)
            db.commit()
            return

        _enqueue_draft(email.id)
        db.commit()
    except Exception:
        db.rollback()
        try:
            em = db.scalar(select(EmailRecord).where(EmailRecord.gmail_message_id == gmail_message_id))
            if em:
                em.last_error = "classify_inbound failed (see logs)"
                db.commit()
        except Exception:
            db.rollback()
        logger.exception("run_classify_inbound failed for %s", gmail_message_id)
        raise
    finally:
        db.close()


def run_draft_and_send_reply(email_id: int) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        email = db.scalars(
            select(EmailRecord)
            .where(EmailRecord.id == email_id)
            .options(
                selectinload(EmailRecord.classification),
                selectinload(EmailRecord.session),
            )
        ).first()
        if not email or not email.classification:
            return
        if email.reply_sent_at or email.reply_skipped_reason:
            return

        clf = email.classification
        if clf.category == "not_relevant":
            email.reply_skipped_reason = "not_relevant"
            db.commit()
            try:
                GmailClient(settings).mark_read(email.gmail_message_id)
            except Exception:
                logger.exception("mark_read failed for %s", email.gmail_message_id)
            return

        gmail = GmailClient(settings)
        inbox_session = email.session
        ctx = _thread_context_for_db(db, inbox_session.id, before_email_id=email.id)
        missing = list(clf.missing_rfq_fields or []) if clf.category == "rfq" else []

        body = draft_reply(
            category=clf.category,
            subject=email.subject,
            customer_body=email.body_text,
            missing_rfq_fields=missing,
            thread_context=ctx,
            settings=settings,
        )
        email.reply_draft = body
        db.flush()

        raw_msg = gmail.get_message(email.gmail_message_id)
        p2 = parse_message_resource(raw_msg)
        in_reply = p2.get("rfc_message_id") or ""

        sent_id = gmail.send_reply_in_thread(
            thread_id=email.thread_id,
            to_address=email.from_address,
            subject=email.subject,
            plain_body=body,
            in_reply_to=in_reply,
            references=in_reply,
        )
        email.outbound_gmail_message_id = sent_id
        email.reply_sent_at = _utcnow()
        email.last_error = None
        db.commit()
        try:
            gmail.mark_read(email.gmail_message_id)
        except Exception:
            logger.exception("mark_read failed for %s", email.gmail_message_id)
    except Exception:
        db.rollback()
        logger.exception("run_draft_and_send_reply failed for email_id=%s", email_id)
        try:
            email = db.get(EmailRecord, email_id)
            if email:
                email.last_error = "draft_and_send_reply failed (see logs)"
                db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()
