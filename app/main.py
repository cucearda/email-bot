from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import init_db
from app.routes.sessions import router as sessions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Logistics Inbox Automator", lifespan=lifespan)
app.include_router(sessions_router)


@app.get("/health")
def health():
    return {"status": "ok"}
