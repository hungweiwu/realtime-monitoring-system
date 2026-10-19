import asyncio

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData

import app.models  # noqa: F401  # 註冊所有 model 到 Base.metadata
from app.db.base import Base
from app.db.session import engine


async def _drop_everything() -> None:
    # 連同 alembic_version 一起清掉，模擬空資料庫
    async with engine.begin() as conn:
        metadata = MetaData()
        await conn.run_sync(metadata.reflect)
        await conn.run_sync(metadata.drop_all)


async def test_migrations_upgrade_downgrade_upgrade_and_match_models() -> None:
    """測試其餘部分用 create_all 建 schema；這裡確認 migration 本身可用且與 model 一致。

    結束時 schema 由 migration 建立，與 create_all 等價，其他測試不受影響。
    """
    cfg = Config("alembic.ini")
    await _drop_everything()

    # env.py 內部用 asyncio.run，不能在測試的 event loop 內直接呼叫，放到執行緒
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
        )
    assert diff == []
