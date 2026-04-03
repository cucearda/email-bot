"""Inbox processing pipeline (used by Dramatiq actors)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from googleapiclient.errors import HttpError

from app.agents.classification import ClassificationOutput, classify_email_text
from app.agents.reply import draft_reply
from app.core.config import get_settings
from app.core.helpers import utcnow
from app.db.session import SessionLocal
from app.domain.categories import CATEGORY_TO_GMAIL_LABEL, EMAIL_CATEGORIES, gmail_label_for_category
from app.integrations.gmail import GmailClient, get_gmail_client
from app.integrations.gmail.client import parse_message_resource
from app.models.orm import ClassificationRecord, EmailRecord, InboxSession

logger = logging.getLogger(__name__)


def _enqueue_draft(email_id: int) -> None:
    """Enqueue reply drafting via Dramatiq."""
    from app.workers.tasks import draft_and_send_reply
    draft_and_send_reply.send(email_id)


def run_resolve_history(user_email: str, history_id: str) -> None:
    """Stage 1: resolve a historyId into individual message IDs and enqueue classification."""
    from app.core.state import get_last_history_id, set_last_history_id
    from app.workers.tasks import classify_inbound

    settings = get_settings()
    gmail = get_gmail_client(settings)

    # Use our stored historyId as the baseline, not the one from the notification.
    # The notification's historyId points at the change itself, so querying from it
    # returns nothing. We need to query from the last ID we successfully processed.
    start_id = get_last_history_id() or history_id
    logger.info("resolve_history: notification_id=%s, using start_id=%s", history_id, start_id)

    message_ids = gmail.history_list(start_id)
    logger.info("history_id=%s resolved to %d message(s)", start_id, len(message_ids))
    for mid in message_ids:
        classify_inbound.send(mid)

    # Advance the stored cursor to the notification's historyId (the latest point)
    set_last_history_id(history_id)


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
        if e.is_outbound:
            parts.append(
                f"[Our reply] Subject: {e.subject}\n{e.body_text}"
            )
        else:
            cat = e.classification.category if e.classification else "unknown"
            parts.append(
                f"[From: {e.from_address}] [Class: {cat}] Subject: {e.subject}\n{e.body_text}"
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
    if cat not in EMAIL_CATEGORIES:
        raise ValueError(
            f"Invalid category {raw.category!r} (normalized to {cat!r}). "
            f"Must be one of: {', '.join(EMAIL_CATEGORIES)}"
        )
    mf = [x.strip().lower().replace(" ", "_") for x in raw.missing_fields]
    allowed = {"origin", "destination", "cargo_type", "weight", "dates"}
    mf = [x for x in mf if x in allowed]
    return ClassificationOutput(category=cat, missing_fields=mf)


def run_classify_inbound(gmail_message_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        try:
            gmail = get_gmail_client(settings)
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

            try:
                raw_msg = gmail.get_message(gmail_message_id)
            except HttpError as e:
                if e.resp.status in (404, 400):
                    logger.warning("Message %s not found (status=%s), skipping", gmail_message_id, e.resp.status)
                    return
                raise
            parsed = parse_message_resource(raw_msg)
            thread_id = parsed["thread_id"]

            # Skip messages sent by ourselves (our own replies)
            profile_email = gmail.get_profile_email()
            from_addr = parsed["from_address"]
            if profile_email and profile_email.lower() in from_addr.lower():
                logger.info("Skipping own message %s", gmail_message_id)
                return

            session = db.scalar(select(InboxSession).where(InboxSession.gmail_thread_id == thread_id))
            if not session:
                session = InboxSession(gmail_thread_id=thread_id)
                db.add(session)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    session = db.scalar(
                        select(InboxSession).where(InboxSession.gmail_thread_id == thread_id)
                    )

            email = existing
            if not email:
                email = EmailRecord(
                    session_id=session.id,
                    gmail_message_id=parsed["gmail_message_id"],
                    thread_id=thread_id,
                    from_address=parsed["from_address"],
                    subject=parsed["subject"],
                    body_text=parsed["body_text"] or parsed["snippet"],
                    received_at=parsed["received_at"] or utcnow(),
                )
                db.add(email)
                try:
                    db.flush()
                except IntegrityError:
                    logger.info("Duplicate email %s — already processed", gmail_message_id)
                    db.rollback()
                    return
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
            raw_out = classify_email_text(thread_context=ctx, current_email=current)
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


def run_draft_and_send_reply(email_id: int) -> None:
    settings = get_settings()
    with SessionLocal() as db:
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
                    get_gmail_client(settings).mark_read(email.gmail_message_id)
                except Exception:
                    logger.exception("mark_read failed for %s", email.gmail_message_id)
                return

            gmail = get_gmail_client(settings)
            inbox_session = email.session
            ctx = _thread_context_for_db(db, inbox_session.id, before_email_id=email.id)
            missing = list(clf.missing_rfq_fields or []) if clf.category == "rfq" else []

            body = draft_reply(
                category=clf.category,
                subject=email.subject,
                customer_body=email.body_text,
                missing_rfq_fields=missing,
                thread_context=ctx,
            )
            email.reply_draft = body
            db.flush()

            try:
                raw_msg = gmail.get_message(email.gmail_message_id)
            except HttpError as e:
                if e.resp.status in (404, 400):
                    email.reply_skipped_reason = f"message_gone ({e.resp.status})"
                    db.commit()
                    logger.warning("Message %s gone (status=%s), skipping reply", email.gmail_message_id, e.resp.status)
                    return
                raise
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
            email.reply_sent_at = utcnow()
            email.last_error = None

            outbound_record = EmailRecord(
                session_id=email.session_id,
                gmail_message_id=sent_id,
                thread_id=email.thread_id,
                from_address=gmail.get_profile_email(),
                subject=email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}",
                body_text=body,
                received_at=utcnow(),
                is_outbound=True,
            )
            db.add(outbound_record)
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
