import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.db.session import init_db
from app.integrations.gmail import get_gmail_client
from app.routes.sessions import router as sessions_router
from app.routes.webhook import router as webhook_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

WATCH_RENEWAL_SECONDS = 6 * 24 * 3600  # renew every 6 days (expires after 7)


async def renew_watch_loop() -> None:
    """Call Gmail watch() on startup and renew before it expires."""
    settings = get_settings()
    gmail = get_gmail_client(settings)
    while True:
        try:
            result = gmail.watch(settings.gcp_project_id, settings.pubsub_topic)
            logger.info("Gmail watch registered, expiration=%s historyId=%s",
                        result.get("expiration"), result.get("historyId"))
            watch_hid = str(result.get("historyId", ""))
            if watch_hid:
                from app.core.state import get_last_history_id, set_last_history_id
                if not get_last_history_id():
                    set_last_history_id(watch_hid)
                    logger.info("Seeded last_history_id=%s from watch()", watch_hid)
        except Exception:
            logger.exception("Failed to register Gmail watch")
        await asyncio.sleep(WATCH_RENEWAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(renew_watch_loop())
    yield
    task.cancel()


app = FastAPI(title="Logistics Inbox Automator", lifespan=lifespan)
app.include_router(sessions_router)
app.include_router(webhook_router)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def ui():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
