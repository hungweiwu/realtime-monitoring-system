"""建立三個種子帳號（admin / user / viewer）。已存在則跳過，重複執行安全。

由 entrypoint 在 migration 之後執行：python -m app.seed
"""

import asyncio
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.models import Role, User

logger = logging.getLogger("app.seed")


async def seed_users() -> None:
    settings = get_settings()
    accounts = [
        (settings.seed_admin_username, settings.seed_admin_password, Role.ADMIN),
        (settings.seed_user_username, settings.seed_user_password, Role.USER),
        (settings.seed_viewer_username, settings.seed_viewer_password, Role.VIEWER),
    ]
    async with SessionLocal() as session:
        for username, password, role in accounts:
            exists = await session.scalar(select(User.id).where(User.username == username))
            if exists is not None:
                logger.info("seed user %s already exists, skipped", username)
                continue
            session.add(User(username=username, hashed_password=hash_password(password), role=role))
            logger.info("seed user %s (%s) created", username, role.value)
        await session.commit()


async def main() -> None:
    setup_logging(get_settings().log_level)
    await seed_users()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
