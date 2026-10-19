from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def authenticate_token(session: AsyncSession, token: str | None) -> User | None:
    """HTTP 與 WebSocket 共用的 token 驗證：token 無效、帳號不存在或已停用都回 None。"""
    user_id = decode_access_token(token) if token else None
    if user_id is None:
        return None
    # 每次都從 DB 讀：Admin 停用帳號或改角色後，舊 token 立即受影響
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    user = await authenticate_token(session, token)
    if user is None:
        raise AuthenticationError("invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: Role) -> Callable[[User], Awaitable[User]]:
    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("insufficient permissions for this operation")
        return user

    return checker
