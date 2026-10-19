import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemLog

logger = logging.getLogger("app.audit")


def log_action(
    session: AsyncSession,
    action: str,
    user_id: int | None = None,
    detail: str | None = None,
    level: str = "INFO",
) -> None:
    """寫入 system_logs 並同步輸出到 stdout。

    不自行 commit：與業務操作同一個 transaction，業務回滾時日誌也不會留下假紀錄。
    """
    session.add(SystemLog(level=level, action=action, user_id=user_id, detail=detail))
    logger.log(logging.getLevelName(level), "%s user_id=%s %s", action, user_id, detail or "")
