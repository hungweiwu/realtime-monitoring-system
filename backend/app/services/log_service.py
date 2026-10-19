import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemLog

logger = logging.getLogger("app.audit")

# detail 含使用者可控字串（username、檔名）：限制長度並跳脫控制字元
MAX_DETAIL_LENGTH = 500
_CONTROL_CHARS = {c: f"\\x{c:02x}" for c in [*range(0x20), 0x7F]} | {
    ord("\n"): "\\n",
    ord("\r"): "\\r",
    ord("\t"): "\\t",
}


def sanitize(text: str) -> str:
    """跳脫換行等控制字元並截斷。

    不處理的話，username 帶 "\n2026-... INFO [app.audit] auth.login" 就能在 stdout 偽造一行
    審計紀錄；超長字串則讓 system_logs 寫入失敗。
    """
    escaped = text.translate(_CONTROL_CHARS)
    if len(escaped) > MAX_DETAIL_LENGTH:
        escaped = escaped[: MAX_DETAIL_LENGTH - 1] + "…"
    return escaped


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
    detail = sanitize(detail) if detail is not None else None
    session.add(SystemLog(level=level, action=action, user_id=user_id, detail=detail))
    logger.log(logging.getLevelName(level), "%s user_id=%s %s", action, user_id, detail or "")
