"""Dramatiq actors — three-stage pipeline."""

from __future__ import annotations

import dramatiq

import app.workers.broker_setup  # noqa: F401 — side effect: set_broker
from app.service.pipeline import run_classify_inbound, run_draft_and_send_reply, run_resolve_history


@dramatiq.actor(options={"dedup_key_arg": 1})  # keyed on history_id
def resolve_history(user_email: str, history_id: str) -> None:
    run_resolve_history(user_email, history_id)


@dramatiq.actor(options={"dedup_key_arg": 0})  # keyed on gmail_message_id
def classify_inbound(gmail_message_id: str) -> None:
    run_classify_inbound(gmail_message_id)


@dramatiq.actor(options={"dedup_key_arg": 0})  # keyed on email_id
def draft_and_send_reply(email_id: int) -> None:
    run_draft_and_send_reply(email_id)
