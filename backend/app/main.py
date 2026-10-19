import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import literal, select

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import SessionLocal, engine
from app.realtime.buffer import MetricBuffer
from app.realtime.generator import run_generator
from app.realtime.ws_manager import ConnectionManager

setup_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    buffer: MetricBuffer = app.state.metric_buffer

    generator_task = flush_task = None
    if settings.enable_generator:
        generator_task = asyncio.create_task(
            run_generator(
                sinks=[buffer.append, app.state.ws_manager.broadcast],
                interval=settings.metric_interval_seconds,
                low=settings.metric_anomaly_low,
                high=settings.metric_anomaly_high,
            )
        )
        flush_task = asyncio.create_task(buffer.run(settings.flush_interval_seconds))
        logger.info("metric generator and flush loop started")

    yield

    # 關機順序：先停產生器（不再有新資料）→ 等 flush 迴圈跑完當次 → 最後 flush 剩餘資料
    if generator_task is not None:
        generator_task.cancel()
        await asyncio.gather(generator_task, return_exceptions=True)
    if flush_task is not None:
        buffer.stop()
        await flush_task
    written = await buffer.flush()
    logger.info("shutdown flush wrote %d metrics (%d left unwritten)", written, buffer.pending)
    await engine.dispose()


app = FastAPI(title="Real-time Monitoring API", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
# 在建立 app 時就建好（而非在 lifespan 內）：不跑 lifespan 的測試 client 也拿得到
app.state.metric_buffer = MetricBuffer(
    SessionLocal,
    batch_size=get_settings().flush_batch_size,
    max_size=get_settings().buffer_max_size,
)
app.state.ws_manager = ConnectionManager(send_timeout=get_settings().ws_send_timeout_seconds)
app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(select(literal(1)))
    except Exception:
        logger.exception("database health check failed")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return JSONResponse(content={"status": "ok", "database": "ok"})
