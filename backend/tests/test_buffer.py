import asyncio
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models import Metric
from app.realtime.buffer import MetricBuffer
from app.realtime.generator import CATEGORIES, generate_metric, is_anomaly

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def point(i: int) -> dict:
    return {
        "value": float(i),
        "category": "temperature",
        "timestamp": T0 + timedelta(seconds=i),
        "is_anomaly": False,
    }


class FailingSession:
    """模擬 DB 斷線：commit 時丟例外。"""

    async def __aenter__(self) -> "FailingSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def add_all(self, items: object) -> None:
        pass

    async def commit(self) -> None:
        raise ConnectionError("database unavailable")


async def metric_count() -> int:
    # 每次開新 session：InnoDB 預設 REPEATABLE READ，同一個 transaction 內看不到其他連線之後的寫入
    async with SessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(Metric)) or 0


async def wait_until(condition) -> None:
    async with asyncio.timeout(2):
        # 要等的是 DB 狀態，沒有 Event 可等，只能輪詢
        while not await condition():  # noqa: ASYNC110
            await asyncio.sleep(0.02)


# --- flush ---


async def test_flush_writes_all_pending_points(db_session: AsyncSession) -> None:
    buffer = MetricBuffer(SessionLocal, batch_size=100, max_size=1000)
    for i in range(3):
        buffer.append(point(i))

    written = await buffer.flush()

    assert written == 3
    assert buffer.pending == 0
    assert await metric_count() == 3


async def test_failed_flush_puts_points_back_in_order() -> None:
    buffer = MetricBuffer(FailingSession, batch_size=100, max_size=1000)
    for i in range(3):
        buffer.append(point(i))

    written = await buffer.flush()

    assert written == 0
    assert [p["value"] for p in buffer.snapshot()] == [0.0, 1.0, 2.0]


async def test_failed_batch_goes_before_points_appended_during_flush() -> None:
    buffer = MetricBuffer(FailingSession, batch_size=100, max_size=1000)

    class AppendThenFail(FailingSession):
        async def commit(self) -> None:
            # 模擬寫入 DB 的 await 期間產生器又 append 了一筆，接著寫入失敗
            buffer.append(point(2))
            raise ConnectionError("database unavailable")

    buffer._session_factory = AppendThenFail
    buffer.append(point(0))
    buffer.append(point(1))

    await buffer.flush()

    # 失敗的批次較舊，必須放回前端，寫入期間新進的接在後面，時間順序才正確
    assert [p["value"] for p in buffer.snapshot()] == [0.0, 1.0, 2.0]


async def test_points_survive_failure_and_are_written_on_next_flush(
    db_session: AsyncSession,
) -> None:
    buffer = MetricBuffer(FailingSession, batch_size=100, max_size=1000)
    buffer.append(point(0))
    await buffer.flush()

    buffer._session_factory = SessionLocal  # DB 恢復
    buffer.append(point(1))
    await buffer.flush()

    values = (await db_session.scalars(select(Metric.value).order_by(Metric.value))).all()
    assert values == [0.0, 1.0]


async def test_buffer_over_max_size_drops_oldest_points() -> None:
    buffer = MetricBuffer(FailingSession, batch_size=100, max_size=3)
    for i in range(5):
        buffer.append(point(i))

    assert [p["value"] for p in buffer.snapshot()] == [2.0, 3.0, 4.0]


async def test_requeue_after_failure_respects_max_size() -> None:
    buffer = MetricBuffer(FailingSession, batch_size=100, max_size=3)
    for i in range(3):
        buffer.append(point(i))

    await buffer.flush()
    buffer.append(point(3))

    assert [p["value"] for p in buffer.snapshot()] == [1.0, 2.0, 3.0]


# --- 背景 flush 迴圈 ---


async def test_reaching_batch_size_flushes_without_waiting_for_interval(
    db_session: AsyncSession,
) -> None:
    buffer = MetricBuffer(SessionLocal, batch_size=5, max_size=1000)
    task = asyncio.create_task(buffer.run(interval=60))
    try:
        for i in range(5):
            buffer.append(point(i))

        async def flushed() -> bool:
            return await metric_count() == 5

        await wait_until(flushed)
    finally:
        buffer.stop()
        await task


async def test_interval_flushes_partial_batch(db_session: AsyncSession) -> None:
    buffer = MetricBuffer(SessionLocal, batch_size=100, max_size=1000)
    task = asyncio.create_task(buffer.run(interval=0.1))
    try:
        buffer.append(point(0))

        async def flushed() -> bool:
            return await metric_count() == 1

        await wait_until(flushed)
    finally:
        buffer.stop()
        await task


async def test_stop_ends_loop_and_final_flush_writes_remaining(db_session: AsyncSession) -> None:
    buffer = MetricBuffer(SessionLocal, batch_size=100, max_size=1000)
    task = asyncio.create_task(buffer.run(interval=60))
    buffer.append(point(0))
    buffer.append(point(1))

    buffer.stop()
    await asyncio.wait_for(task, timeout=2)
    await buffer.flush()

    assert await metric_count() == 2


# --- 產生器 ---


def test_is_anomaly_outside_bounds() -> None:
    assert is_anomaly(95, low=10, high=90)
    assert is_anomaly(5, low=10, high=90)
    assert not is_anomaly(50, low=10, high=90)
    assert not is_anomaly(90, low=10, high=90)
    assert not is_anomaly(10, low=10, high=90)


def test_generate_metric_shape() -> None:
    metric = generate_metric(random.Random(0), low=10, high=90)

    assert metric["category"] in CATEGORIES
    assert metric["timestamp"].tzinfo is not None
    assert metric["is_anomaly"] == is_anomaly(metric["value"], low=10, high=90)
