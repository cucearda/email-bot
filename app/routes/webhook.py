"""Pub/Sub push endpoint for Gmail notifications."""

from __future__ import annotations

import base64
import json
import logging

from fastapi import APIRouter, Request, Response
from app.core.config import get_settings
from app.workers.tasks import resolve_history

router = APIRouter(tags=["webhook"])
logger = logging.getLogger(__name__)


def _verify_webhook_token(request: Request) -> bool:
    """Check the ?token= query param matches the configured webhook secret."""
    secret = get_settings().webhook_secret
    if not secret:
        logger.warning("WEBHOOK_SECRET not configured — webhook is unauthenticated")
        return True
    token = request.query_params.get("token", "")
    return token == secret


@router.post("/webhook/gmail")
async def gmail_push(request: Request) -> Response:
    """Receive Pub/Sub push, enqueue resolve_history, return 200 immediately."""

    if not _verify_webhook_token(request):
        logger.warning("Webhook request with invalid token — rejected")
        return Response(status_code=403)

    body = await request.json()
    message = body.get("message", {})
    data_b64 = message.get("data", "")
    if not data_b64:
        logger.warning("Pub/Sub push with no data")
        return Response(status_code=400)

    try:
        payload = json.loads(base64.urlsafe_b64decode(data_b64 + "==="))
    except Exception:
        logger.exception("Failed to decode Pub/Sub data")
        return Response(status_code=400)

    user_email = payload.get("emailAddress", "")
    history_id = str(payload.get("historyId", ""))

    if not history_id:
        logger.warning("Pub/Sub push missing historyId")
        return Response(status_code=400)

    logger.info("Gmail push: user=%s historyId=%s", user_email, history_id)
    try:
        resolve_history.send(user_email, history_id)
    except Exception:
        logger.exception("Failed to enqueue resolve_history")
        return Response(status_code=500)
    return Response(status_code=200)
