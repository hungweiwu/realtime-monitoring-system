from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models import User
from app.realtime.buffer import MetricBuffer
from app.services import metric_service
from tests.conftest import create_user

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def point(seconds: int) -> dict:
    return {
        "value": float(seconds),
        "category": "temperature",
        "timestamp": T0 + timedelta(seconds=seconds),
        "is_anomaly": False,
    }


async def test_latest_sees_batch_flushed_after_request_session_started(
    db_session: AsyncSession,
) -> None:
    # 模擬請求：驗證使用者時已在同一個 session 讀過 DB（InnoDB REPEATABLE READ 固定了 read view）
    await create_user(db_session, "alice")
    await db_session.scalar(select(User.id))

    buffer = MetricBuffer(SessionLocal, batch_size=100, max_size=1000)
    buffer.append(point(0))
    buffer.append(point(1))
    # 請求進行中，flush 把這批資料 commit 進 DB 並清空 buffer
    assert await buffer.flush() == 2

    points = await metric_service.latest(db_session, buffer, limit=10)

    assert [p.value for p in points] == [0.0, 1.0]


async def test_latest_keeps_objects_loaded_earlier_in_the_request_usable(
    db_session: AsyncSession,
) -> None:
    # CurrentUser 在驗證時載入；結束交易若用 rollback 會讓它過期，之後存取屬性會在 async 下失敗
    user = await create_user(db_session, "alice")
    # 模擬 get_current_user 在同一個 session 查過 DB：此時有進行中的交易
    await db_session.scalar(select(User.id))
    buffer = MetricBuffer(SessionLocal, batch_size=100, max_size=1000)

    await metric_service.latest(db_session, buffer, limit=10)

    assert user.username == "alice"


async def test_latest_merges_unflushed_points_without_duplicates(
    db_session: AsyncSession,
) -> None:
    buffer = MetricBuffer(SessionLocal, batch_size=100, max_size=1000)
    buffer.append(point(0))
    await buffer.flush()
    buffer.append(point(1))

    points = await metric_service.latest(db_session, buffer, limit=10)

    assert [p.value for p in points] == [0.0, 1.0]
