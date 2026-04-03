"""Configure Dramatiq broker — Redis if available, otherwise StubBroker."""

import logging

import dramatiq
from dramatiq.brokers.stub import StubBroker
from app.core.config import get_settings
from dramatiq.brokers.redis import RedisBroker
import redis as redis_lib

logger = logging.getLogger(__name__)


def setup_broker() -> None:
    settings = get_settings()
    try:
        redis_client = redis_lib.Redis.from_url(settings.redis_url)
        redis_client.ping()

        broker = RedisBroker(url=settings.redis_url)

        from app.workers.dedup import RedisDedup
        broker.add_middleware(RedisDedup(client=redis_client))

        dramatiq.set_broker(broker)
        logger.info("Dramatiq broker: Redis (%s) with dedup middleware", settings.redis_url)
    except Exception:
        broker = StubBroker()
        broker.emit_after("process_boot")
        dramatiq.set_broker(broker)
        logger.warning("Redis unavailable — using StubBroker (tasks run synchronously, no dedup)")


setup_broker()
