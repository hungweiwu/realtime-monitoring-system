import asyncio
import logging
from typing import Protocol

from app.realtime.generator import MetricPoint
from app.schemas.metric import MetricPointOut

logger = logging.getLogger(__name__)


class TextSocket(Protocol):
    async def send_text(self, data: str) -> None: ...


class ConnectionManager:
    """管理 WebSocket 連線並廣播即時資料。"""

    def __init__(self, send_timeout: float) -> None:
        self._connections: set[TextSocket] = set()
        self._send_timeout = send_timeout

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
                self.remove(ws)
                logger.info("dropped websocket connection: %r", result)
