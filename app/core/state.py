"""Persist last-seen Gmail historyId across restarts."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = Path("./gmail_history_id.txt")


def get_last_history_id() -> str | None:
    try:
        return _STATE_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def set_last_history_id(history_id: str) -> None:
    _STATE_FILE.write_text(history_id)
