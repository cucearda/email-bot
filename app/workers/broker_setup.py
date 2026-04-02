"""Configure Dramatiq broker before any actors are defined."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings


def setup_broker() -> None:
    url = get_settings().redis_url
    dramatiq.set_broker(RedisBroker(url=url))


setup_broker()
