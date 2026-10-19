import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from app.models import Metric
from app.realtime.generator import MetricPoint

logger = logging.getLogger(__name__)


class MetricBuffer:
    """即時資料的記憶體 buffer，累積後整批寫入 DB。

    觸發 flush 的兩個條件：達到 batch_size（append 時 set event，立即喚醒），
    或距離上次 flush 已過 interval 秒（wait_for 逾時）。
    """

    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[Any]],
        batch_size: int,
        max_size: int,
    ) -> None:
        self._session_factory = session_factory
        self._batch_size = batch_size
        self._max_size = max_size
        self._items: list[MetricPoint] = []
        # 正在寫入 DB、尚未 commit 的那一批：snapshot 仍要看得到，避免 /metrics/latest 漏掉
        self._inflight: list[MetricPoint] = []
        self._flush_requested = asyncio.Event()
        self._flush_lock = asyncio.Lock()
        self._stopping = False
        self.dropped = 0

    @property
    def pending(self) -> int:
        return len(self._items)

    def snapshot(self) -> list[MetricPoint]:
        """尚未確定寫入 DB 的資料（寫入中的批次 + 待寫），依時間順序。"""
        return self._inflight + self._items

    def clear(self) -> None:
        self._items = []
        self._inflight = []

    def append(self, point: MetricPoint) -> None:
        self._items.append(point)
        self._trim()
        if len(self._items) >= self._batch_size:
            self._flush_requested.set()

    def _trim(self) -> None:
        overflow = len(self._items) - self._max_size
        if overflow > 0:
            # DB 長時間寫不進去時才會發生：丟最舊的，保留最新的資料
            del self._items[:overflow]
            self.dropped += overflow
            logger.warning("metric buffer full, dropped %d oldest points", overflow)

    async def flush(self) -> int:
        """寫入目前所有待寫資料，回傳寫入筆數；失敗時把資料放回 buffer 前端並回傳 0。"""
        async with self._flush_lock:
            if not self._items:
                return 0
            # 先換成新的空 list 再寫入：這兩步之間沒有 await，產生器不會插隊；
            # 寫入期間產生器 append 的資料進新 list，不會被這次 flush 漏掉或重複寫入
            batch, self._items = self._items, []
            self._inflight = batch
            try:
                async with self._session_factory() as session:
                    # 每次都建新的 ORM 物件：失敗的 session 裡的物件狀態不可靠，不重用
                    session.add_all([Metric(**point) for point in batch])
                    await session.commit()
            except Exception:
                logger.exception("metric flush failed, %d points returned to buffer", len(batch))
                # 放回前端以保持時間順序；寫入期間新進的資料接在後面
                self._items = batch + self._items
                self._trim()
                return 0
            finally:
                self._inflight = []
            logger.info("flushed %d metrics (pending %d)", len(batch), len(self._items))
            return len(batch)

    async def run(self, interval: float) -> None:
        """背景 flush 迴圈，呼叫 stop() 後在當次 flush 完成後結束。"""
        while not self._stopping:
            try:
                await asyncio.wait_for(self._flush_requested.wait(), timeout=interval)
            except TimeoutError:
                pass
            # 先 clear 再 flush：flush 期間新進的資料若達門檻會重新 set，不會被漏掉
            self._flush_requested.clear()
            if self._stopping:
                break
            written = await self.flush()
            if written == 0 and self._items:
                # 寫入失敗：等一個完整間隔再重試，避免 buffer 已達門檻時不停重試、打爆 DB
                await asyncio.sleep(interval)

    def stop(self) -> None:
        # 用旗標而不是 cancel task：cancel 若發生在 commit 中途，那一批資料會遺失
        self._stopping = True
        self._flush_requested.set()
