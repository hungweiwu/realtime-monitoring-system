import logging
import time

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Metric, Record, SystemLog, User
from app.realtime.buffer import MetricBuffer
from app.schemas.admin import (
    DatabaseCheck,
    DbStatus,
    LogParams,
    MetricHistoryParams,
    PageParams,
    UserUpdate,
)
from app.services.log_service import log_action

logger = logging.getLogger(__name__)

TABLES = {"users": User, "records": Record, "metrics": Metric, "system_logs": SystemLog}


async def _page(session: AsyncSession, stmt, count_stmt, params: PageParams):
    total = await session.scalar(count_stmt)
    items = (
        await session.scalars(stmt.offset((params.page - 1) * params.size).limit(params.size))
    ).all()
    return list(items), total or 0


async def list_users(session: AsyncSession, params: PageParams) -> tuple[list[User], int]:
    return await _page(
        session,
        select(User).order_by(User.id),
        select(func.count()).select_from(User),
        params,
    )


async def update_user(session: AsyncSession, user_id: int, data: UserUpdate, actor: User) -> User:
    if user_id == actor.id:
        # 避免 Admin 停用或降級自己，導致系統沒有 Admin
        raise PermissionDeniedError("admins cannot change their own role or status")
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("user", user_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    log_action(
        session,
        "admin.user_update",
        user_id=actor.id,
        detail=f"target={user.username} "
        + " ".join(f"{k}={getattr(v, 'value', v)}" for k, v in changes.items()),
    )
    await session.commit()
    return user


async def list_logs(session: AsyncSession, params: LogParams) -> tuple[list[SystemLog], int]:
    conditions = []
    if params.level is not None:
        conditions.append(SystemLog.level == params.level.upper())
    if params.action is not None:
        conditions.append(SystemLog.action == params.action)
    if params.start is not None:
        conditions.append(SystemLog.created_at >= params.start)
    if params.end is not None:
        conditions.append(SystemLog.created_at <= params.end)
    return await _page(
        session,
        select(SystemLog)
        .where(*conditions)
        .order_by(SystemLog.created_at.desc(), SystemLog.id.desc()),
        select(func.count()).select_from(SystemLog).where(*conditions),
        params,
    )


async def list_metrics(
    session: AsyncSession, params: MetricHistoryParams
) -> tuple[list[Metric], int]:
    conditions = []
    if params.anomaly_only:
        conditions.append(Metric.is_anomaly.is_(True))
    if params.category is not None:
        conditions.append(Metric.category == params.category)
    if params.start is not None:
        conditions.append(Metric.timestamp >= params.start)
    if params.end is not None:
        conditions.append(Metric.timestamp <= params.end)
    return await _page(
        session,
        select(Metric).where(*conditions).order_by(Metric.timestamp.desc(), Metric.id.desc()),
        select(func.count()).select_from(Metric).where(*conditions),
        params,
    )


def _pool_status(engine: AsyncEngine) -> dict[str, int | str]:
    pool = engine.pool
    status: dict[str, int | str] = {"class": type(pool).__name__}
    # QueuePool 才有這些統計；NullPool（測試用）沒有
    if not hasattr(pool, "checkedout"):
        return status
    status["size"] = pool.size()
    status["checked_in"] = pool.checkedin()
    status["checked_out"] = pool.checkedout()
    # overflow() 是「借出數 - size」，未用滿時為負數；只回報實際使用中的超量連線，較直觀
    status["overflow_in_use"] = max(0, pool.overflow())
    status["max_overflow"] = get_settings().db_max_overflow
    return status


async def db_status(
    session: AsyncSession, engine: AsyncEngine, buffer: MetricBuffer, ws_connections: int
) -> DbStatus:
    started = time.perf_counter()
    try:
        # 健康檢查也用 ORM 表達式 select(literal(1))，不寫 SQL 字串
        await session.execute(select(literal(1)))
        check = DatabaseCheck(ok=True, latency_ms=round((time.perf_counter() - started) * 1000, 2))
    except Exception:
        logger.exception("db status check failed")
        return DbStatus(
            database=DatabaseCheck(ok=False, latency_ms=None),
            pool=_pool_status(engine),
            tables={},
            buffer={"pending": buffer.pending, "dropped": buffer.dropped},
            websocket_connections=ws_connections,
        )

    tables = {
        name: await session.scalar(select(func.count()).select_from(model)) or 0
        for name, model in TABLES.items()
    }
    return DbStatus(
        database=check,
        pool=_pool_status(engine),
        tables=tables,
        buffer={"pending": buffer.pending, "dropped": buffer.dropped},
        websocket_connections=ws_connections,
    )
