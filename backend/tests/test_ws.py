import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.logging import TokenRedactingFilter
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models import Metric, Role
from app.realtime.ws_manager import ConnectionManager
from tests.conftest import auth_headers, create_user

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def point(seconds: int, value: float = 50.0) -> dict:
    return {
        "value": value,
        "category": "temperature",
        "timestamp": T0 + timedelta(seconds=seconds),
        "is_anomaly": False,
    }


def make_user_token(username: str, is_active: bool = True) -> str:
    # TestClient 測試是同步函式，用 asyncio.run 在獨立 loop 建資料
    # （測試 engine 為 NullPool，連線不綁 loop）
    async def _create() -> int:
        async with SessionLocal() as session:
            user = await create_user(session, username, is_active=is_active)
            return user.id

    return create_access_token(asyncio.run(_create()))


# --- WebSocket 驗證 ---


def test_ws_with_valid_token_receives_broadcast() -> None:
    token = make_user_token("alice")

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/ws/metrics?token={token}") as ws:
            # websocket_connect 在 accept 後就返回，伺服器驗證 token、註冊連線還要一點時間；
            # 先等註冊完成再廣播，否則訊息送不到、receive 會永遠等下去
            deadline = time.monotonic() + 2
            while app.state.ws_manager.count == 0:
                assert time.monotonic() < deadline, "websocket was not registered"
                time.sleep(0.01)
            client.portal.call(app.state.ws_manager.broadcast, point(0, value=42.0))
            message = ws.receive_json()

    assert message["value"] == 42.0
    assert message["timestamp"] == "2026-10-20T00:00:00Z"


@pytest.mark.parametrize("query", ["?token=not-a-jwt", ""])
def test_ws_with_invalid_or_missing_token_is_closed_with_1008(query: str) -> None:
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/ws/metrics{query}") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()

    assert exc_info.value.code == 1008


def test_ws_with_disabled_user_is_closed_with_1008() -> None:
    token = make_user_token("alice", is_active=False)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/ws/metrics?token={token}") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()

    assert exc_info.value.code == 1008


# --- ConnectionManager 廣播 ---


class FakeSocket:
    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.sent: list[str] = []
        self.closed_with: int | None = None

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise RuntimeError("connection reset")
        await asyncio.sleep(self.delay)
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


async def test_broadcast_sends_same_message_to_all_connections() -> None:
    manager = ConnectionManager(send_timeout=1)
    a, b = FakeSocket(), FakeSocket()
    manager.add(a)
    manager.add(b)

    await manager.broadcast(point(0))

    assert len(a.sent) == len(b.sent) == 1
    assert json.loads(a.sent[0]) == json.loads(b.sent[0])


async def test_broadcast_drops_failing_and_slow_connections_without_blocking() -> None:
    manager = ConnectionManager(send_timeout=0.1)
    healthy, slow, broken = FakeSocket(), FakeSocket(delay=5), FakeSocket(fail=True)
    for ws in (healthy, slow, broken):
        manager.add(ws)

    async with asyncio.timeout(1):  # 慢連線不能拖住整次廣播
        await manager.broadcast(point(0))

    assert len(healthy.sent) == 1
    assert manager.count == 1


async def test_dropped_connections_are_closed_so_clients_reconnect() -> None:
    manager = ConnectionManager(send_timeout=0.1)
    healthy, slow, broken = FakeSocket(), FakeSocket(delay=5), FakeSocket(fail=True)
    for ws in (healthy, slow, broken):
        manager.add(ws)

    await manager.broadcast(point(0))
    await asyncio.sleep(0.05)  # close 在背景 task 執行

    # 只從名單移除而不關閉的話，用戶端收不到 onclose、不會重連，畫面停在「連線中」
    assert slow.closed_with == 1013
    assert broken.closed_with == 1013
    assert healthy.closed_with is None


# --- token 遮蔽 ---


def test_token_is_redacted_from_uvicorn_log_records() -> None:
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        0,
        '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:5000", "/api/v1/ws/metrics?token=eyJhbGciOi.secret.sig"),
        None,
    )

    TokenRedactingFilter().filter(record)

    message = record.getMessage()
    assert "eyJhbGciOi" not in message
    assert "token=***" in message


def test_redacted_access_log_still_formats_with_uvicorn_access_formatter() -> None:
    # uvicorn 的 AccessFormatter 會把 record.args 解包成 5 個值；filter 不能破壞 args
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/v1/metrics/latest?token=secret.jwt", "1.1", 200),
        None,
    )

    TokenRedactingFilter().filter(record)
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)

    assert "secret.jwt" not in line
    assert "token=***" in line


# --- /metrics/latest ---


async def test_latest_merges_db_and_unflushed_buffer_in_time_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)
    db_session.add_all([Metric(**point(0)), Metric(**point(1))])
    await db_session.commit()
    app.state.metric_buffer.append(point(2))

    resp = await client.get("/api/v1/metrics/latest", headers=auth_headers(viewer))

    assert resp.status_code == 200
    timestamps = [m["timestamp"] for m in resp.json()]
    assert timestamps == [
        "2026-10-20T00:00:00Z",
        "2026-10-20T00:00:01Z",
        "2026-10-20T00:00:02Z",
    ]


async def test_latest_returns_only_most_recent_limit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    db_session.add_all([Metric(**point(i)) for i in range(5)])
    await db_session.commit()
    app.state.metric_buffer.append(point(5))

    resp = await client.get(
        "/api/v1/metrics/latest", params={"limit": 3}, headers=auth_headers(user)
    )

    assert [m["timestamp"][-3:] for m in resp.json()] == ["03Z", "04Z", "05Z"]


async def test_latest_limit_over_500_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")

    resp = await client.get(
        "/api/v1/metrics/latest", params={"limit": 501}, headers=auth_headers(user)
    )

    assert resp.status_code == 422


async def test_latest_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/metrics/latest")
    assert resp.status_code == 401
