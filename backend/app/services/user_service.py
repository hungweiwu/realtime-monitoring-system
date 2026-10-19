from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import hash_password, verify_password
from app.models import Role, User
from app.schemas.user import UserRegister
from app.services.log_service import log_action

# 帳號不存在與密碼錯誤回同一個訊息，避免從回應內容枚舉帳號
INVALID_CREDENTIALS = "incorrect username or password"


async def register(session: AsyncSession, data: UserRegister) -> User:
    exists = await session.scalar(select(User.id).where(User.username == data.username))
    if exists is not None:
        raise ConflictError("username already exists")

    user = User(
        username=data.username, hashed_password=hash_password(data.password), role=Role.USER
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        # 兩個請求同時註冊同名帳號時，由 unique constraint 擋下
        await session.rollback()
        raise ConflictError("username already exists") from None
    log_action(session, "auth.register", user_id=user.id, detail=f"username={user.username}")
    await session.commit()
    return user


async def authenticate(session: AsyncSession, username: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.username == username))
    if not verify_password(password, user.hashed_password if user else None):
        log_action(session, "auth.login_failed", detail=f"username={username}", level="WARNING")
        await session.commit()
        raise AuthenticationError(INVALID_CREDENTIALS)
    if not user.is_active:
        log_action(
            session,
            "auth.login_failed",
            user_id=user.id,
            detail="account disabled",
            level="WARNING",
        )
        await session.commit()
        raise AuthenticationError("account is disabled")

    log_action(session, "auth.login", user_id=user.id)
    await session.commit()
    return user
