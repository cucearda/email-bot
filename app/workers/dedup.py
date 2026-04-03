"""Dramatiq middleware: skip actors that are already running for the same key.

Uses a Redis SET-NX lock with a TTL. If the lock already exists the message
is acknowledged immediately (dropped), preventing duplicate processing.

Configure via the ``dedup_keys`` dict passed to the constructor::

    RedisDedup(client=redis_client, dedup_keys={
        "classify_inbound": 0,   # arg index
        "resolve_history": 1,
    })
"""

from __future__ import annotations

import logging

import dramatiq

logger = logging.getLogger(__name__)

DEFAULT_TTL_MS = 10 * 60 * 1000  # 10 minutes


class RedisDedup(dramatiq.Middleware):
    """Drop duplicate messages based on a Redis lock per (actor, key)."""

    def __init__(
        self,
        *,
        client,
        dedup_keys: dict[str, int | str] | None = None,
        ttl_ms: int = DEFAULT_TTL_MS,
    ) -> None:
        self._client = client
        self._ttl_ms = ttl_ms
        self._dedup_keys: dict[str, int | str] = dedup_keys or {}

    def _lock_key(self, actor_name: str, dedup_value: str) -> str:
        return f"dramatiq:dedup:{actor_name}:{dedup_value}"

    def before_process_message(self, broker, message):
        dedup_arg = self._dedup_keys.get(message.actor_name)
        if dedup_arg is None:
            return

        # Resolve the dedup value from args or kwargs
        if isinstance(dedup_arg, int):
            dedup_value = str(message.args[dedup_arg])
        else:
            dedup_value = str(message.kwargs[dedup_arg])

        key = self._lock_key(message.actor_name, dedup_value)
        acquired = self._client.set(key, "1", nx=True, px=self._ttl_ms)
        if not acquired:
            logger.info(
                "Dedup: dropping duplicate %s(%s)", message.actor_name, dedup_value
            )
            message.fail()
            return False

        # Stash the key so we can clean up after processing
        message.options["dedup_redis_key"] = key

    def after_process_message(self, broker, message, *, result=None, exception=None):
        key = message.options.get("dedup_redis_key")
        if key:
            self._client.delete(key)

    def after_skip_message(self, broker, message):
        key = message.options.get("dedup_redis_key")
        if key:
            self._client.delete(key)
