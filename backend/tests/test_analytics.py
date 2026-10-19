from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Metric, Record, Role, User
from tests.conftest import auth_headers, create_user

T0 = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)


async def add_records(session: AsyncSession, owner: User, rows: list[tuple]) -> None:
    for value, category, ts in rows:
        session.add(
            Record(title="r", value=value, category=category, timestamp=ts, created_by=owner.id)
        )
    await session.commit()


async def add_metrics(session: AsyncSession, rows: list[tuple]) -> None:
    for value, category, ts in rows:
        session.add(Metric(value=value, category=category, timestamp=ts, is_anomaly=False))
    await session.commit()


async def get(client: AsyncClient, user: User, path: str, **params):
    return await client.get(f"/api/v1/analytics/{path}", params=params, headers=auth_headers(user))


# --- summary ---


async def test_summary_of_records(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [(v, "temperature", T0) for v in (1.0, 2.0, 3.0, 10.0)])

    resp = await get(client, user, "summary", source="records")

    assert resp.status_code == 200
    assert resp.json() == {"count": 4, "sum": 16.0, "avg": 4.0, "max": 10.0, "min": 1.0}


async def test_summary_defaults_to_metrics_source(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [(100.0, "temperature", T0)])
    await add_metrics(db_session, [(5.0, "pressure", T0), (7.0, "pressure", T0)])

    body = (await get(client, user, "summary")).json()

    assert body["count"] == 2
    assert body["avg"] == 6.0


async def test_summary_applies_category_and_time_filters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_metrics(
        db_session,
        [
            (1.0, "pressure", T0),
            (2.0, "pressure", T0 + timedelta(hours=2)),
            (3.0, "humidity", T0),
        ],
    )

    body = (
        await get(
            client,
            user,
            "summary",
            category="pressure",
            start=T0.isoformat(),
            end=(T0 + timedelta(hours=1)).isoformat(),
        )
    ).json()

    assert body["count"] == 1
    assert body["sum"] == 1.0


async def test_summary_of_empty_set_returns_zero_count_and_nulls(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    body = (await get(client, user, "summary")).json()

    assert body == {"count": 0, "sum": None, "avg": None, "max": None, "min": None}


# --- by-category ---


async def test_by_category_returns_one_row_per_category(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_metrics(
        db_session, [(1.0, "pressure", T0), (3.0, "pressure", T0), (10.0, "humidity", T0)]
    )

    body = (await get(client, user, "by-category")).json()

    assert body == [
        {"category": "humidity", "count": 1, "avg": 10.0, "max": 10.0, "min": 10.0},
        {"category": "pressure", "count": 2, "avg": 2.0, "max": 3.0, "min": 1.0},
    ]


# --- trend ---


async def test_trend_groups_by_hour_in_time_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_metrics(
        db_session,
        [
            (3.0, "c", T0 + timedelta(minutes=80)),
            (1.0, "c", T0 + timedelta(minutes=10)),
            (2.0, "c", T0 + timedelta(minutes=50)),
        ],
    )

    body = (await get(client, user, "trend", interval="hour")).json()

    assert [(p["bucket"], p["count"], p["avg"]) for p in body] == [
        ("2026-10-20T00:00:00Z", 2, 1.5),
        ("2026-10-20T01:00:00Z", 1, 3.0),
    ]


async def test_trend_by_day_uses_taipei_day_boundaries(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    # 15:30Z = 台北 10/19 23:30；16:30Z = 台北 10/20 00:30，雖然 UTC 同一天，台北是不同天
    await add_metrics(
        db_session,
        [
            (1.0, "c", datetime(2026, 10, 19, 15, 30, tzinfo=UTC)),
            (2.0, "c", datetime(2026, 10, 19, 16, 30, tzinfo=UTC)),
        ],
    )

    body = (await get(client, user, "trend", interval="day")).json()

    assert [p["bucket"] for p in body] == ["2026-10-18T16:00:00Z", "2026-10-19T16:00:00Z"]


async def test_trend_by_minute(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    await add_metrics(
        db_session,
        [(1.0, "c", T0 + timedelta(seconds=5)), (2.0, "c", T0 + timedelta(seconds=65))],
    )

    body = (await get(client, user, "trend", interval="minute")).json()

    assert [p["bucket"] for p in body] == ["2026-10-20T00:00:00Z", "2026-10-20T00:01:00Z"]


# --- 驗證與權限 ---


async def test_invalid_source_returns_422(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    assert (await get(client, user, "summary", source="users")).status_code == 422


async def test_invalid_interval_returns_422(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    assert (await get(client, user, "trend", interval="week")).status_code == 422


async def test_naive_start_returns_422(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    resp = await get(client, user, "summary", start="2026-10-20T00:00:00")
    assert resp.status_code == 422


async def test_viewer_can_read_analytics(client: AsyncClient, db_session: AsyncSession) -> None:
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)
    assert (await get(client, viewer, "summary")).status_code == 200


async def test_analytics_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/analytics/summary")
    assert resp.status_code == 401
