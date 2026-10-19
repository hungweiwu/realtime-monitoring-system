import asyncio
import contextlib
import logging
from typing import Protocol

from app.realtime.generator import MetricPoint
from app.schemas.metric import MetricPointOut

logger = logging.getLogger(__name__)


# 1013 Try Again Later：非 1008，前端會依退避間隔自動重連
SLOW_CONSUMER_CLOSE_CODE = 1013


class TextSocket(Protocol):
    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


class ConnectionManager:
    """管理 WebSocket 連線並廣播即時資料。"""

    def __init__(self, send_timeout: float) -> None:
        self._connections: set[TextSocket] = set()
        self._send_timeout = send_timeout
        # 保留背景 close task 的參考，避免執行中被 GC 回收
        self._closing: set[asyncio.Task[None]] = set()

    @property
    def count(self) -> int:
        return len(self._connections)

    def add(self, ws: TextSocket) -> None:
        self._connections.add(ws)

    def remove(self, ws: TextSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, point: MetricPoint) -> None:
        if not self._connections:
            return
        # 只序列化一次，所有連線送同一份字串
        message = MetricPointOut.model_validate(point).model_dump_json()
        connections = list(self._connections)
        # 並行送出且每條設 timeout：逐一 await 時，一條慢連線會拖住產生器，所有人的資料都延遲
        results = await asyncio.gather(
            *(asyncio.wait_for(ws.send_text(message), self._send_timeout) for ws in connections),
            return_exceptions=True,
        )
        for ws, result in zip(connections, results, strict=True):
            if isinstance(result, BaseException):
                self._drop(ws, result)

    def _drop(self, ws: TextSocket, reason: BaseException) -> None:
        """移出廣播名單並關閉連線。

        只移出名單不關閉的話，連線仍開著、handler 卡在 receive，用戶端收不到 onclose
        也不會重連，畫面停在「連線中」卻再也沒有資料。close 放背景執行，不拖慢這次廣播。
        """
        self.remove(ws)
        logger.info("dropped websocket connection: %r", reason)
        task = asyncio.create_task(self._close(ws))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _close(self, ws: TextSocket) -> None:
        # 連線可能早已斷開；關閉失敗不影響其他人
        with contextlib.suppress(Exception):
            await asyncio.wait_for(ws.close(code=SLOW_CONSUMER_CLOSE_CODE), self._send_timeout)
