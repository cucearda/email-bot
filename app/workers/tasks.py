"""Dramatiq actors — three-stage email processing pipeline."""

from __future__ import annotations

import dramatiq

import app.workers.broker_setup  # noqa: F401 — side effect: set_broker
from app.service.email import (
    classify_inbound as do_classify,
    draft_and_send_reply as do_draft_and_send,
    resolve_history as do_resolve_history,
)


@dramatiq.actor
def resolve_history(user_email: str, history_id: str) -> None:
    message_ids = do_resolve_history(user_email, history_id)
    for mid in message_ids:
        classify_inbound.send(mid)


@dramatiq.actor
def classify_inbound(gmail_message_id: str) -> None:
    email_id = do_classify(gmail_message_id)
    if email_id:
        draft_and_send_reply.send(email_id)


@dramatiq.actor
def draft_and_send_reply(email_id: int) -> None:
    do_draft_and_send(email_id)
