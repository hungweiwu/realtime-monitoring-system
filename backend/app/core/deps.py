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


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    user_id = decode_access_token(token)
    if user_id is None:
        raise AuthenticationError("invalid or expired token")
    # 每次都從 DB 讀：Admin 停用帳號或改角色後，舊 token 立即受影響
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: Role) -> Callable[[User], Awaitable[User]]:
    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("insufficient permissions for this operation")
        return user

    return checker
