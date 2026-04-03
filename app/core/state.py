"""Persist last-seen Gmail historyId in the database."""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.orm import AppState

logger = logging.getLogger(__name__)

_KEY = "gmail_history_id"


def get_last_history_id() -> str | None:
    with SessionLocal() as db:
        row = db.get(AppState, _KEY)
        return row.value if row else None


def set_last_history_id(history_id: str) -> None:
    with SessionLocal() as db:
        # BEGIN IMMEDIATE gives us an exclusive write lock on SQLite,
        # preventing concurrent writers from interleaving.
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(AppState, _KEY)
        if row:
            row.value = history_id
        else:
            db.add(AppState(key=_KEY, value=history_id))
        db.commit()
