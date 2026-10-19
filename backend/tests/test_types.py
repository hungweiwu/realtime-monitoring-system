from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Metric


async def test_utc_datetime_round_trips_as_same_instant_in_utc(db_session: AsyncSession) -> None:
    taipei = datetime(2026, 10, 20, 8, 0, 0, 123456, tzinfo=ZoneInfo("Asia/Taipei"))
    metric = Metric(value=1.5, category="cpu", timestamp=taipei, is_anomaly=False)
    db_session.add(metric)
    await db_session.commit()
    db_session.expunge_all()

    stored = (await db_session.execute(select(Metric.timestamp))).scalar_one()

    assert stored == taipei
    assert stored.tzinfo == UTC
    assert stored.hour == 0
    assert stored.microsecond == 123456


async def test_utc_datetime_rejects_naive_datetime(db_session: AsyncSession) -> None:
    db_session.add(Metric(value=1.0, category="cpu", timestamp=datetime(2026, 1, 1)))

    with pytest.raises(StatementError, match="naive datetime"):
        await db_session.commit()
