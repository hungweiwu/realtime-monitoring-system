from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.core.exceptions import register_exception_handlers
from app.core.security import create_access_token
from app.models import Role, SystemLog, User
from app.seed import seed_users
from tests.conftest import create_user


async def login(client: AsyncClient, username: str, password: str):
    return await client.post(
        "/api/v1/auth/login", data={"username": username, "password": password}
    )


# --- 註冊 ---


async def test_register_creates_user_with_default_role(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"username": "alice", "password": "password123"}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    assert body["role"] == "user"
    assert "password" not in body and "hashed_password" not in body


async def test_register_duplicate_username_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, "alice")

    resp = await client.post(
        "/api/v1/auth/register", json={"username": "alice", "password": "password123"}
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


async def test_register_with_role_field_is_rejected_and_not_created(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "mallory", "password": "password123", "role": "admin"},
    )

    assert resp.status_code == 422
    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 0


async def test_register_rejects_short_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"username": "alice", "password": "short"}
    )
    assert resp.status_code == 422


async def test_register_rejects_invalid_username(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"username": "a b!", "password": "password123"}
    )
    assert resp.status_code == 422


# --- 登入 ---


async def test_login_returns_bearer_token_usable_on_me(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, "alice", password="password123")

    resp = await login(client, "alice", "password123")
    assert resp.status_code == 200
    token = resp.json()
    assert token["token_type"] == "bearer"

    me = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


async def test_wrong_password_and_unknown_user_return_identical_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, "alice", password="password123")

    wrong_password = await login(client, "alice", "wrong-password")
    unknown_user = await login(client, "nobody", "wrong-password")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


async def test_login_disabled_user_returns_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, "alice", password="password123", is_active=False)

    resp = await login(client, "alice", "password123")

    assert resp.status_code == 401


async def test_login_success_and_failure_are_written_to_system_logs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, "alice", password="password123")

    await login(client, "alice", "password123")
    await login(client, "alice", "wrong-password")

    actions = (await db_session.scalars(select(SystemLog.action))).all()
    assert "auth.login" in actions
    assert "auth.login_failed" in actions


# --- token 驗證 ---


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


async def test_me_with_garbage_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


async def test_me_with_expired_token_returns_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice")
    token = create_access_token(user.id, expires_delta=timedelta(seconds=-1))

    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401


async def test_disabling_user_invalidates_existing_token_immediately(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, "alice", password="password123")
    token = (await login(client, "alice", "password123")).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 200

    user.is_active = False
    await db_session.commit()

    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 401


# --- 角色檢查 ---


def build_role_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/admin-only")
    async def admin_only(
        user: Annotated[User, Depends(require_role(Role.ADMIN))],
    ) -> dict[str, str]:
        return {"username": user.username}

    return app


async def test_require_role_allows_matching_role_and_rejects_others(
    db_session: AsyncSession,
) -> None:
    admin = await create_user(db_session, "boss", role=Role.ADMIN)
    viewer = await create_user(db_session, "watcher", role=Role.VIEWER)

    transport = ASGITransport(app=build_role_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        ok = await c.get(
            "/admin-only", headers={"Authorization": f"Bearer {create_access_token(admin.id)}"}
        )
        denied = await c.get(
            "/admin-only", headers={"Authorization": f"Bearer {create_access_token(viewer.id)}"}
        )

    assert ok.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"


# --- 種子帳號 ---


async def test_seed_users_creates_three_roles_and_is_idempotent(db_session: AsyncSession) -> None:
    await seed_users()
    await seed_users()

    rows = (await db_session.execute(select(User.username, User.role))).all()
    assert len(rows) == 3
    assert {role for _, role in rows} == {Role.ADMIN, Role.USER, Role.VIEWER}
