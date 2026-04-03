"""Configure Dramatiq broker — Redis if available, otherwise StubBroker."""

import logging

import dramatiq
from dramatiq.brokers.stub import StubBroker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def setup_broker() -> None:
    settings = get_settings()
    try:
        from dramatiq.brokers.redis import RedisBroker
        broker = RedisBroker(url=settings.redis_url)
        broker.connection.ping()
        dramatiq.set_broker(broker)
        logger.info("Dramatiq broker: Redis (%s)", settings.redis_url)
    except Exception:
        broker = StubBroker()
        broker.emit_after("process_boot")
        dramatiq.set_broker(broker)
        logger.warning("Redis unavailable — using StubBroker (tasks run synchronously)")


setup_broker()
