import json
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record, Role, SystemLog, User
from tests.conftest import auth_headers, create_user

HEADER = "title,value,category,timestamp\n"


async def upload(client: AsyncClient, user: User, filename: str, content: str | bytes):
    data = content.encode() if isinstance(content, str) else content
    return await client.post(
        "/api/v1/records/import",
        files={"file": (filename, data)},
        headers=auth_headers(user),
    )


async def test_csv_import_inserts_valid_rows_and_reports_invalid_ones(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    csv = (
        HEADER
        + "ok-1,10.5,temperature,2026-10-20T08:00:00+08:00\n"
        + "bad-value,not-a-number,temperature,2026-10-20T08:00:00+08:00\n"
        + "ok-2,3,pressure,2026-10-20T09:00:00Z\n"
        + ",1,pressure,2026-10-20T09:00:00Z\n"
    )

    resp = await upload(client, user, "records.csv", csv)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success_count"] == 2
    assert body["failed_count"] == 2
    assert [e["row"] for e in body["errors"]] == [2, 4]
    assert "value" in body["errors"][0]["message"]
    titles = (await db_session.scalars(select(Record.title))).all()
    assert sorted(titles) == ["ok-1", "ok-2"]


async def test_imported_records_are_owned_by_uploader(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    await upload(client, user, "r.csv", HEADER + "a,1,c,2026-10-20T00:00:00Z\n")

    owner = await db_session.scalar(select(Record.created_by))
    assert owner == user.id


async def test_naive_timestamp_is_treated_as_taipei_time(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    await upload(client, user, "r.csv", HEADER + "a,1,c,2026-10-20 08:00:00\n")

    stored = await db_session.scalar(select(Record.timestamp))
    assert stored == datetime(2026, 10, 20, 0, 0, tzinfo=UTC)


async def test_aware_timestamp_keeps_its_own_offset(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    await upload(client, user, "r.csv", HEADER + "a,1,c,2026-10-20T08:00:00Z\n")

    stored = await db_session.scalar(select(Record.timestamp))
    assert stored == datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


async def test_csv_with_utf8_bom_is_accepted(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    # Excel 另存 CSV 會在開頭加 BOM，第一個欄位名會變成 "﻿title"
    content = "﻿" + HEADER + "溫度,1,c,2026-10-20T00:00:00Z\n"

    resp = await upload(client, user, "r.csv", content.encode("utf-8"))

    assert resp.json()["success_count"] == 1


async def test_csv_missing_required_column_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await upload(client, user, "r.csv", "title,value\na,1\n")

    assert resp.status_code == 422


async def test_json_import_inserts_rows(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    rows = [
        {"title": "a", "value": 1, "category": "c", "timestamp": "2026-10-20T00:00:00Z"},
        {"title": "b", "value": "oops", "category": "c", "timestamp": "2026-10-20T00:00:00Z"},
    ]

    resp = await upload(client, user, "records.json", json.dumps(rows))

    body = resp.json()
    assert body["success_count"] == 1
    assert body["errors"][0]["row"] == 2


async def test_json_that_is_not_a_list_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await upload(client, user, "r.json", json.dumps({"title": "a"}))

    assert resp.status_code == 422


async def test_malformed_json_returns_422(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")

    resp = await upload(client, user, "r.json", "[{not json")

    assert resp.status_code == 422


async def test_csv_field_over_csv_module_limit_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    # csv 模組預設單一欄位上限 131072 字元，超過會丟 csv.Error
    content = HEADER + "x" * 200_000 + ",1,c,2026-10-20T00:00:00Z\n"

    resp = await upload(client, user, "r.csv", content)

    assert resp.status_code == 422


async def test_deeply_nested_json_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await upload(client, user, "r.json", "[" * 100_000 + "]" * 100_000)

    assert resp.status_code == 422


async def test_unsupported_extension_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await upload(client, user, "records.txt", HEADER)

    assert resp.status_code == 422


async def test_file_over_5mb_returns_413(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    content = HEADER + "x" * (5 * 1024 * 1024)

    resp = await upload(client, user, "big.csv", content)

    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_more_than_10000_rows_returns_413(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    content = HEADER + "a,1,c,2026-10-20T00:00:00Z\n" * 10_001

    resp = await upload(client, user, "many.csv", content)

    assert resp.status_code == 413
    count = (await db_session.scalars(select(Record.id))).all()
    assert count == []


async def test_viewer_cannot_import(client: AsyncClient, db_session: AsyncSession) -> None:
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)

    resp = await upload(client, viewer, "r.csv", HEADER + "a,1,c,2026-10-20T00:00:00Z\n")

    assert resp.status_code == 403


async def test_import_is_written_to_system_logs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    await upload(client, user, "r.csv", HEADER + "a,1,c,2026-10-20T00:00:00Z\n")

    log = await db_session.scalar(select(SystemLog).where(SystemLog.action == "record.import"))
    assert log is not None
    assert "success=1" in log.detail
