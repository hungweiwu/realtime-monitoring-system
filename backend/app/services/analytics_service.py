"""資料分析：records 與 metrics 共用 value / category / timestamp 三欄，聚合邏輯共用。

全部以 ORM 表達式（func.count / avg / max / min、group_by）組成，不寫 SQL 字串。
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Metric, Record
from app.schemas.analytics import (
    AnalyticsParams,
    CategoryStat,
    Summary,
    TrendParams,
    TrendPoint,
)

MODELS: dict[str, type[Record] | type[Metric]] = {"records": Record, "metrics": Metric}

# MariaDB DATE_FORMAT：把時間截到區間起點
BUCKET_FORMATS = {
    "minute": "%Y-%m-%d %H:%i:00",
    "hour": "%Y-%m-%d %H:00:00",
    "day": "%Y-%m-%d 00:00:00",
}


def conditions(model: type[Record] | type[Metric], params: AnalyticsParams) -> list:
    conditions: list[ColumnElement[bool]] = []
    if params.category is not None:
        conditions.append(model.category == params.category)
    if params.start is not None:
        conditions.append(model.timestamp >= params.start)
    if params.end is not None:
        conditions.append(model.timestamp <= params.end)
    return conditions


def analytics_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().analytics_timezone)


def _utc_offset(tz: ZoneInfo) -> str:
    """把時區換成 CONVERT_TZ 用的數字偏移（例如 +08:00）。

    用數字偏移 MariaDB 不需匯入時區資料表；代價是有日光節約的時區在切換前後的分組會差一小時，
    台北沒有日光節約，不受影響。
    """
    offset = datetime.now(tz).utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


async def summary(session: AsyncSession, params: AnalyticsParams) -> Summary:
    model = MODELS[params.source]
    stmt = select(
        func.count(model.id),
        func.sum(model.value),
        func.avg(model.value),
        func.max(model.value),
        func.min(model.value),
    ).where(*conditions(model, params))
    count, total, avg, max_, min_ = (await session.execute(stmt)).one()
    return Summary(count=count, sum=total, avg=avg, max=max_, min=min_)


async def by_category(session: AsyncSession, params: AnalyticsParams) -> list[CategoryStat]:
    model = MODELS[params.source]
    stmt = (
        select(
            model.category,
            func.count(model.id),
            func.avg(model.value),
            func.max(model.value),
            func.min(model.value),
        )
        .where(*conditions(model, params))
        .group_by(model.category)
        .order_by(model.category)
    )
    rows = (await session.execute(stmt)).all()
    return [
        CategoryStat(category=c, count=n, avg=avg, max=max_, min=min_)
        for c, n, avg, max_, min_ in rows
    ]


async def trend(session: AsyncSession, params: TrendParams) -> list[TrendPoint]:
    model = MODELS[params.source]
    tz = analytics_timezone()
    # DB 存 UTC；先轉成分析時區再截斷，「一天」才是台北的 00:00–24:00 而非 UTC 的
    local_ts = func.convert_tz(model.timestamp, "+00:00", _utc_offset(tz))
    bucket = func.date_format(local_ts, BUCKET_FORMATS[params.interval]).label("bucket")
    stmt = (
        select(
            bucket,
            func.count(model.id),
            func.avg(model.value),
            func.max(model.value),
            func.min(model.value),
        )
        .where(*conditions(model, params))
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(stmt)).all()
    return [
        TrendPoint(
            bucket=datetime.strptime(b, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).astimezone(UTC),
            count=n,
            avg=avg,
            max=max_,
            min=min_,
        )
        for b, n, avg, max_, min_ in rows
    ]
