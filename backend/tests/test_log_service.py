from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemLog
from app.services.log_service import MAX_DETAIL_LENGTH, log_action


async def test_control_characters_are_escaped_so_log_lines_cannot_be_forged(
    db_session: AsyncSession,
) -> None:
    forged = "x\n2026-10-19 12:00:00 INFO [app.audit] auth.login user_id=1"

    log_action(db_session, "auth.login_failed", detail=f"username={forged}")
    await db_session.commit()

    detail = await db_session.scalar(select(SystemLog.detail))
    assert "\n" not in detail
    assert "\\n2026-10-19" in detail


async def test_long_detail_is_truncated(db_session: AsyncSession) -> None:
    log_action(db_session, "auth.login_failed", detail="u" * 100_000)
    await db_session.commit()

    detail = await db_session.scalar(select(SystemLog.detail))
    assert len(detail) <= MAX_DETAIL_LENGTH
