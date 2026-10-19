import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record
from tests.conftest import auth_headers, create_user

RECORD = {"title": "t", "value": 1, "category": "c"}


@pytest.mark.parametrize(
    "timestamp", ["0001-01-01T00:00:00+08:00", "1969-12-31T00:00:00Z", "2100-01-01T00:00:00Z"]
)
async def test_create_with_out_of_range_timestamp_returns_422(
    client: AsyncClient, db_session: AsyncSession, timestamp: str
) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.post(
        "/api/v1/records", json={**RECORD, "timestamp": timestamp}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


async def test_list_with_extreme_end_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get(
        "/api/v1/records", params={"end": "9999-12-31T23:59:59-01:00"}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


async def test_analytics_with_extreme_start_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get(
        "/api/v1/analytics/summary",
        params={"start": "0001-01-01T00:00:00+08:00"},
        headers=auth_headers(user),
    )

    assert resp.status_code == 422


async def test_import_reports_out_of_range_row_and_keeps_valid_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    csv = (
        "title,value,category,timestamp\n"
        "ok,1,c,2026-10-20 08:00:00\n"
        "ancient,1,c,0001-01-01 00:00:00\n"
    )

    resp = await client.post(
        "/api/v1/records/import",
        files={"file": ("r.csv", csv.encode())},
        headers=auth_headers(user),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success_count"] == 1
    assert body["errors"][0]["row"] == 2
    assert (await db_session.scalars(select(Record.title))).all() == ["ok"]
