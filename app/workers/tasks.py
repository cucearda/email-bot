"""Dramatiq actors."""

from __future__ import annotations

import dramatiq

import app.workers.broker_setup  # noqa: F401 — side effect: set_broker
from app.service.pipeline import run_classify_inbound, run_draft_and_send_reply


@dramatiq.actor
def classify_inbound(gmail_message_id: str) -> None:
    run_classify_inbound(gmail_message_id)


@dramatiq.actor
def draft_and_send_reply(email_id: int) -> None:
    run_draft_and_send_reply(email_id)
