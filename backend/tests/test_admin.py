from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Metric, Role, SystemLog
from tests.conftest import auth_headers, create_user

T0 = datetime(2026, 10, 20, tzinfo=UTC)

ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/users"),
    ("PATCH", "/api/v1/admin/users/1"),
    ("GET", "/api/v1/admin/logs"),
    ("GET", "/api/v1/admin/db-status"),
    ("GET", "/api/v1/admin/metrics"),
]


# --- 權限 ---


@pytest.mark.parametrize("role", [Role.USER, Role.VIEWER])
@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
async def test_non_admin_gets_403_on_admin_endpoints(
    client: AsyncClient, db_session: AsyncSession, role: Role, method: str, path: str
) -> None:
    user = await create_user(db_session, "someone", role=role)

    resp = await client.request(method, path, json={}, headers=auth_headers(user))

    assert resp.status_code == 403


# --- 使用者管理 ---


async def test_list_users_is_paginated(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    for i in range(4):
        await create_user(db_session, f"user{i}")

    resp = await client.get(
        "/api/v1/admin/users", params={"page": 2, "size": 2}, headers=auth_headers(admin)
    )

    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert "hashed_password" not in body["items"][0]


async def test_admin_changes_role_and_it_applies_immediately(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    target = await create_user(db_session, "alice", role=Role.USER)

    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}", json={"role": "viewer"}, headers=auth_headers(admin)
    )

    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"
    # 同一個舊 token，角色立即變成 viewer：不能再新增資料
    record = {"title": "t", "value": 1, "category": "c", "timestamp": "2026-10-20T00:00:00Z"}
    denied = await client.post("/api/v1/records", json=record, headers=auth_headers(target))
    assert denied.status_code == 403


async def test_disabling_user_revokes_existing_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    target = await create_user(db_session, "alice")
    target_headers = auth_headers(target)

    await client.patch(
        f"/api/v1/admin/users/{target.id}", json={"is_active": False}, headers=auth_headers(admin)
    )

    assert (await client.get("/api/v1/users/me", headers=target_headers)).status_code == 401


async def test_admin_cannot_modify_self(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)

    resp = await client.patch(
        f"/api/v1/admin/users/{admin.id}", json={"is_active": False}, headers=auth_headers(admin)
    )

    assert resp.status_code == 403


async def test_patch_missing_user_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)

    resp = await client.patch(
        "/api/v1/admin/users/999999", json={"role": "user"}, headers=auth_headers(admin)
    )

    assert resp.status_code == 404


@pytest.mark.parametrize(
    "payload", [{"role": None}, {"username": "renamed"}, {"role": "superuser"}]
)
async def test_patch_user_rejects_invalid_payload(
    client: AsyncClient, db_session: AsyncSession, payload: dict
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    target = await create_user(db_session, "alice")

    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}", json=payload, headers=auth_headers(admin)
    )

    assert resp.status_code == 422


async def test_user_update_is_written_to_system_logs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    target = await create_user(db_session, "alice")

    await client.patch(
        f"/api/v1/admin/users/{target.id}", json={"role": "viewer"}, headers=auth_headers(admin)
    )

    resp = await client.get(
        "/api/v1/admin/logs", params={"action": "admin.user_update"}, headers=auth_headers(admin)
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["user_id"] == admin.id
    assert "role" in items[0]["detail"]


# --- 系統日誌 ---


async def test_logs_filter_by_level_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    for i, level in enumerate(["INFO", "WARNING", "WARNING"]):
        db_session.add(SystemLog(level=level, action=f"a{i}", created_at=T0 + timedelta(minutes=i)))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/admin/logs", params={"level": "WARNING"}, headers=auth_headers(admin)
    )

    assert [log["action"] for log in resp.json()["items"]] == ["a2", "a1"]


async def test_logs_filter_by_time_range(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    for i in range(3):
        db_session.add(SystemLog(level="INFO", action=f"a{i}", created_at=T0 + timedelta(hours=i)))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/admin/logs",
        params={
            "start": (T0 + timedelta(hours=1)).isoformat(),
            "end": (T0 + timedelta(hours=1)).isoformat(),
        },
        headers=auth_headers(admin),
    )

    assert [log["action"] for log in resp.json()["items"]] == ["a1"]


# --- DB 狀態 ---


async def test_db_status_reports_connection_tables_and_buffer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)

    resp = await client.get("/api/v1/admin/db-status", headers=auth_headers(admin))

    body = resp.json()
    assert body["database"]["ok"] is True
    assert body["tables"]["users"] == 1
    assert set(body["tables"]) == {"users", "records", "metrics", "system_logs"}
    assert "pending" in body["buffer"]
    assert "pool" in body


# --- metrics 歷史 ---


async def test_metrics_history_anomaly_only_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    for i in range(4):
        db_session.add(
            Metric(
                value=float(i),
                category="c",
                timestamp=T0 + timedelta(seconds=i),
                is_anomaly=i % 2 == 1,
            )
        )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/admin/metrics", params={"anomaly_only": True}, headers=auth_headers(admin)
    )

    body = resp.json()
    assert body["total"] == 2
    assert [m["value"] for m in body["items"]] == [3.0, 1.0]
