from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Metric
from app.realtime.buffer import MetricBuffer
from app.schemas.metric import MetricPointOut


async def latest(session: AsyncSession, buffer: MetricBuffer, limit: int) -> list[MetricPointOut]:
    """最新 limit 筆即時資料（由舊到新），合併 DB 與尚未寫入的 buffer。

    順序很重要：
    1. 先取 buffer snapshot（含寫入中的批次），再查 DB。反過來的話，若 flush 在「查完 DB」與
       「取 snapshot」之間 commit，該批資料兩邊都不在，會漏掉一段。
    2. 查 DB 前先 rollback：驗證使用者時同一個 session 已讀過 DB，InnoDB REPEATABLE READ 的
       read view 從那時固定，看不到之後才 commit 的批次。rollback 結束這個 transaction，
       下一個查詢會拿到新的 read view。
    """
    # 只驗證需要的最後 limit 筆：DB 斷線時 buffer 可能累積上萬筆
    pending = [MetricPointOut.model_validate(p) for p in buffer.snapshot()[-limit:]]
    await session.rollback()
    rows = (
        await session.scalars(select(Metric).order_by(Metric.timestamp.desc()).limit(limit))
    ).all()
    points = [MetricPointOut.model_validate(r) for r in rows] + pending
    # 同一批可能同時出現在 DB 與 snapshot（snapshot 後才 commit），以 (timestamp, category) 去重
    unique = {(p.timestamp, p.category): p for p in points}
    return sorted(unique.values(), key=lambda p: p.timestamp)[-limit:]
