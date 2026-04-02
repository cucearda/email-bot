"""CLI: cron-friendly poll + one-time Gmail OAuth."""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import get_settings
from app.integrations.gmail import GmailClient, run_oauth_local_server

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def cmd_gmail_auth() -> None:
    settings = get_settings()
    run_oauth_local_server(settings)
    logger.info("Wrote token to %s", settings.gmail_token_path)


def cmd_poll_inbox() -> None:
    from app.workers.tasks import classify_inbound

    settings = get_settings()
    gmail = GmailClient(settings)
    ids = gmail.list_unread_message_ids(max_results=50)
    logger.info("Enqueue classify_inbound for %d message(s)", len(ids))
    for mid in ids:
        try:
            classify_inbound.send(mid)
        except Exception:
            logger.exception("Failed to enqueue %s", mid)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Inbox automator CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gmail-auth", help="OAuth browser flow; writes token.json")
    sub.add_parser("poll-inbox", help="List unread inbox mail and enqueue classify_inbound")

    args = p.parse_args(argv)
    if args.cmd == "gmail-auth":
        cmd_gmail_auth()
    elif args.cmd == "poll-inbox":
        cmd_poll_inbox()
    else:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
