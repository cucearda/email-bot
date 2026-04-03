"""Configure Dramatiq broker with Redis."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings


def setup_broker() -> None:
    settings = get_settings()
    broker = RedisBroker(url=settings.redis_url)
    dramatiq.set_broker(broker)


setup_broker()
