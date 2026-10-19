import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import literal, select

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import engine

setup_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(title="Real-time Monitoring API", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)


@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(select(literal(1)))
    except Exception:
        logger.exception("database health check failed")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return JSONResponse(content={"status": "ok", "database": "ok"})
