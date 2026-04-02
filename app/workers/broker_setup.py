"""Configure Dramatiq broker before any actors are defined.

Uses in-memory StubBroker (no Redis). The cron CLI runs the pipeline synchronously
via ``app.service.pipeline``; actors remain for a future Redis-backed worker setup.
"""

import dramatiq
from dramatiq.brokers.stub import StubBroker


def setup_broker() -> None:
    dramatiq.set_broker(StubBroker())


setup_broker()
