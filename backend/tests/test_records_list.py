from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record, Role, User
from tests.conftest import auth_headers, create_user

BASE_TIME = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)


async def add_records(session: AsyncSession, owner: User, specs: list[dict]) -> None:
    for i, spec in enumerate(specs):
        session.add(
            Record(
                title=spec.get("title", f"record-{i}"),
                value=spec.get("value", float(i)),
                category=spec.get("category", "temperature"),
                timestamp=spec.get("timestamp", BASE_TIME + timedelta(minutes=i)),
                created_by=owner.id,
            )
        )
    await session.commit()


async def list_records(client: AsyncClient, user: User, **params) -> dict:
    resp = await client.get("/api/v1/records", params=params, headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- 分頁 ---


async def test_pagination_returns_page_slice_and_total(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [{} for _ in range(25)])

    page3 = await list_records(client, user, page=3, size=10)

    assert page3["total"] == 25
    assert page3["page"] == 3
    assert page3["size"] == 10
    assert len(page3["items"]) == 5


async def test_consecutive_pages_do_not_overlap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    # 全部同一個 timestamp：排序值相同時仍須穩定分頁
    await add_records(db_session, user, [{"timestamp": BASE_TIME} for _ in range(10)])

    page1 = await list_records(client, user, page=1, size=5)
    page2 = await list_records(client, user, page=2, size=5)

    ids1 = {r["id"] for r in page1["items"]}
    ids2 = {r["id"] for r in page2["items"]}
    assert len(ids1 | ids2) == 10


async def test_size_over_100_returns_422(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get("/api/v1/records", params={"size": 101}, headers=auth_headers(user))

    assert resp.status_code == 422


# --- 篩選 ---


async def test_filter_by_category(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    await add_records(
        db_session,
        user,
        [{"category": "temperature"}, {"category": "pressure"}, {"category": "pressure"}],
    )

    result = await list_records(client, user, category="pressure")

    assert result["total"] == 2
    assert {r["category"] for r in result["items"]} == {"pressure"}


async def test_filter_by_time_range_is_inclusive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [{} for _ in range(10)])  # 每筆間隔 1 分鐘

    result = await list_records(
        client,
        user,
        start=(BASE_TIME + timedelta(minutes=2)).isoformat(),
        end=(BASE_TIME + timedelta(minutes=4)).isoformat(),
    )

    assert result["total"] == 3


async def test_filter_time_range_accepts_other_timezones(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [{} for _ in range(10)])

    # 2026-10-20T08:05+08:00 == 00:05Z，應包含第 5 筆之後
    result = await list_records(client, user, start="2026-10-20T08:05:00+08:00")

    assert result["total"] == 5


async def test_filter_by_value_range(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [{"value": v} for v in (1.0, 5.0, 10.0, 50.0)])

    result = await list_records(client, user, min_value=5, max_value=10)

    assert sorted(r["value"] for r in result["items"]) == [5.0, 10.0]


async def test_filters_combine(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    await add_records(
        db_session,
        user,
        [
            {"category": "pressure", "value": 5.0},
            {"category": "pressure", "value": 50.0},
            {"category": "temperature", "value": 5.0},
        ],
    )

    result = await list_records(client, user, category="pressure", max_value=10)

    assert result["total"] == 1


async def test_naive_start_returns_422(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get(
        "/api/v1/records", params={"start": "2026-10-20T00:00:00"}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


async def test_start_after_end_returns_422(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get(
        "/api/v1/records",
        params={"start": "2026-10-21T00:00:00Z", "end": "2026-10-20T00:00:00Z"},
        headers=auth_headers(user),
    )

    assert resp.status_code == 422


# --- 排序 ---


async def test_sort_by_value_ascending(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [{"value": v} for v in (3.0, 1.0, 2.0)])

    result = await list_records(client, user, sort_by="value", order="asc")

    assert [r["value"] for r in result["items"]] == [1.0, 2.0, 3.0]


async def test_default_sort_is_timestamp_descending(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    await add_records(db_session, user, [{} for _ in range(3)])

    result = await list_records(client, user)

    timestamps = [r["timestamp"] for r in result["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_sort_by_unlisted_column_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get(
        "/api/v1/records", params={"sort_by": "created_by"}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


# --- 權限 ---


async def test_viewer_can_list(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await create_user(db_session, "alice")
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)
    await add_records(db_session, owner, [{}])

    result = await list_records(client, viewer)

    assert result["total"] == 1


async def test_list_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/records")
    assert resp.status_code == 401
