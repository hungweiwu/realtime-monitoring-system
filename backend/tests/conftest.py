from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  # 註冊所有 model 到 Base.metadata
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Role, User


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    async with SessionLocal() as session:
        # 子表先刪，避免 FK 擋住
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def create_user(
    session: AsyncSession,
    username: str,
    password: str = "password123",
    role: Role = Role.USER,
    is_active: bool = True,
) -> User:
    user = User(
        username=username,
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    return user


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
