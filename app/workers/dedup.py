"""Dramatiq middleware: skip actors that are already running for the same key.

Uses a Redis SET-NX lock with a TTL. If the lock already exists the message
is acknowledged immediately (dropped), preventing duplicate processing.

Actors opt in by setting ``options={"dedup_key_arg": 0}`` (index of the arg
used as the dedup key) or ``options={"dedup_key_arg": "kwarg_name"}``.
"""

from __future__ import annotations

import logging

import dramatiq

logger = logging.getLogger(__name__)

DEFAULT_TTL_MS = 10 * 60 * 1000  # 10 minutes


class RedisDedup(dramatiq.Middleware):
    """Drop duplicate messages based on a Redis lock per (actor, key)."""

    def __init__(self, *, client, ttl_ms: int = DEFAULT_TTL_MS) -> None:
        self._client = client
        self._ttl_ms = ttl_ms

    def _lock_key(self, actor_name: str, dedup_value: str) -> str:
        return f"dramatiq:dedup:{actor_name}:{dedup_value}"

    def before_process_message(self, broker, message):
        actor = broker.get_actor(message.actor_name)
        dedup_arg = actor.options.get("dedup_key_arg")
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
