import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypedDict

logger = logging.getLogger(__name__)

CATEGORIES = ("temperature", "pressure", "humidity", "vibration")


class MetricPoint(TypedDict):
    value: float
    category: str
    timestamp: datetime
    is_anomaly: bool


def is_anomaly(value: float, low: float, high: float) -> bool:
    return value < low or value > high


def generate_metric(rng: random.Random, low: float, high: float) -> MetricPoint:
    # 平均 50、標準差 20：約 5% 的點會落在 10 / 90 之外，Demo 時看得到告警
    value = round(rng.gauss(50, 20), 2)
    return {
        "value": value,
        "category": rng.choice(CATEGORIES),
        "timestamp": datetime.now(UTC),
        "is_anomaly": is_anomaly(value, low, high),
    }


async def run_generator(
    sinks: list[Callable[[MetricPoint], Awaitable[None] | None]],
    interval: float,
    low: float,
    high: float,
) -> None:
    """每 interval 秒產生一筆資料，依序交給每個 sink（寫入 buffer、WebSocket 廣播）。

    每個 sink 都拿到同一筆資料。不用共用的 asyncio.Queue：Queue 的每筆資料只會被一個消費者取走，
    兩個消費者會各拿到約一半。
    """
    rng = random.Random()
    while True:
        point = generate_metric(rng, low, high)
        for sink in sinks:
            try:
                result = sink(point)
                if result is not None:
                    await result
            except Exception:
                # 單一 sink 出錯不能讓產生器停掉
                logger.exception("metric sink failed")
        await asyncio.sleep(interval)
