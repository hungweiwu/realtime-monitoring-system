from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, SystemLog
from tests.conftest import auth_headers, create_user

RECORD = {
    "title": "line-3 temperature",
    "value": 72.5,
    "category": "temperature",
    "timestamp": "2026-10-20T08:00:00+08:00",
}


async def create_record(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:
    resp = await client.post("/api/v1/records", json={**RECORD, **overrides}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- 新增 ---


async def test_user_creates_record_owned_by_self(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice", role=Role.USER)

    resp = await client.post("/api/v1/records", json=RECORD, headers=auth_headers(user))

    assert resp.status_code == 201
    body = resp.json()
    assert body["created_by"] == user.id
    assert body["title"] == RECORD["title"]
    assert body["timestamp"] == "2026-10-20T00:00:00Z"


async def test_viewer_cannot_create_record(client: AsyncClient, db_session: AsyncSession) -> None:
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)

    resp = await client.post("/api/v1/records", json=RECORD, headers=auth_headers(viewer))

    assert resp.status_code == 403


async def test_create_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/records", json=RECORD)
    assert resp.status_code == 401


async def test_create_with_naive_timestamp_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.post(
        "/api/v1/records",
        json={**RECORD, "timestamp": "2026-10-20T08:00:00"},
        headers=auth_headers(user),
    )

    assert resp.status_code == 422


async def test_create_cannot_set_created_by(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.post(
        "/api/v1/records", json={**RECORD, "created_by": 999}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


# --- 讀取 ---


async def test_viewer_can_read_record(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)
    record = await create_record(client, auth_headers(user))

    resp = await client.get(f"/api/v1/records/{record['id']}", headers=auth_headers(viewer))

    assert resp.status_code == 200
    assert resp.json()["id"] == record["id"]


async def test_get_missing_record_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get("/api/v1/records/999999", headers=auth_headers(user))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- 修改 ---


async def test_patch_updates_only_given_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    record = await create_record(client, auth_headers(user))

    resp = await client.patch(
        f"/api/v1/records/{record['id']}", json={"value": 99.9}, headers=auth_headers(user)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == 99.9
    assert body["title"] == record["title"]
    assert body["updated_at"] > record["updated_at"]


async def test_patch_with_null_field_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    record = await create_record(client, auth_headers(user))

    resp = await client.patch(
        f"/api/v1/records/{record['id']}", json={"title": None}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


async def test_patch_with_naive_timestamp_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    record = await create_record(client, auth_headers(user))

    resp = await client.patch(
        f"/api/v1/records/{record['id']}",
        json={"timestamp": "2026-10-20T08:00:00"},
        headers=auth_headers(user),
    )

    assert resp.status_code == 422


async def test_user_cannot_patch_others_record(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await create_user(db_session, "alice")
    other = await create_user(db_session, "bob")
    record = await create_record(client, auth_headers(owner))

    resp = await client.patch(
        f"/api/v1/records/{record['id']}", json={"value": 1.0}, headers=auth_headers(other)
    )

    assert resp.status_code == 403


async def test_admin_can_patch_any_record(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await create_user(db_session, "alice")
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    record = await create_record(client, auth_headers(owner))

    resp = await client.patch(
        f"/api/v1/records/{record['id']}", json={"value": 1.0}, headers=auth_headers(admin)
    )

    assert resp.status_code == 200
    assert resp.json()["created_by"] == owner.id


async def test_put_replaces_all_fields(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    record = await create_record(client, auth_headers(user))
    replacement = {
        "title": "line-4 pressure",
        "value": 1.2,
        "category": "pressure",
        "timestamp": "2026-10-21T00:00:00Z",
    }

    resp = await client.put(
        f"/api/v1/records/{record['id']}", json=replacement, headers=auth_headers(user)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert {k: body[k] for k in replacement} == replacement


async def test_put_with_missing_field_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    record = await create_record(client, auth_headers(user))

    resp = await client.put(
        f"/api/v1/records/{record['id']}", json={"title": "only title"}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


# --- 刪除 ---


async def test_user_deletes_own_record(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, "alice")
    record = await create_record(client, auth_headers(user))

    resp = await client.delete(f"/api/v1/records/{record['id']}", headers=auth_headers(user))
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/records/{record['id']}", headers=auth_headers(user))
    assert resp.status_code == 404


async def test_user_cannot_delete_others_record(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await create_user(db_session, "alice")
    other = await create_user(db_session, "bob")
    record = await create_record(client, auth_headers(owner))

    resp = await client.delete(f"/api/v1/records/{record['id']}", headers=auth_headers(other))

    assert resp.status_code == 403


async def test_viewer_cannot_delete_record(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await create_user(db_session, "alice")
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)
    record = await create_record(client, auth_headers(owner))

    resp = await client.delete(f"/api/v1/records/{record['id']}", headers=auth_headers(viewer))

    assert resp.status_code == 403


async def test_delete_missing_record_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)

    resp = await client.delete("/api/v1/records/999999", headers=auth_headers(admin))

    assert resp.status_code == 404


# --- 日誌 ---


async def test_write_operations_are_written_to_system_logs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    headers = auth_headers(user)
    record = await create_record(client, headers)
    await client.patch(f"/api/v1/records/{record['id']}", json={"value": 2.0}, headers=headers)
    await client.delete(f"/api/v1/records/{record['id']}", headers=headers)

    actions = (await db_session.scalars(select(SystemLog.action))).all()
    assert {"record.create", "record.update", "record.delete"} <= set(actions)
