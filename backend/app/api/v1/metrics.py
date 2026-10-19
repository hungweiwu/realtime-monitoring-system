from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.core.deps import CurrentUser, SessionDep
from app.models import Metric
from app.schemas.metric import LatestParams, MetricPointOut

router = APIRouter(prefix="/metrics", tags=["realtime"])


@router.get("/latest", response_model=list[MetricPointOut])
async def latest_metrics(
    params: Annotated[LatestParams, Query()],
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> list[MetricPointOut]:
    """最新 N 筆即時資料（時間由舊到新），包含尚未寫入 DB 的 buffer 資料。"""
    rows = (
        await session.scalars(select(Metric).order_by(Metric.timestamp.desc()).limit(params.limit))
    ).all()
    points = [MetricPointOut.model_validate(r) for r in rows]
    points += [MetricPointOut.model_validate(p) for p in request.app.state.metric_buffer.snapshot()]
    # 寫入中的批次可能同時出現在 DB 與 buffer，以 timestamp 去重
    unique = {(p.timestamp, p.category): p for p in points}
    ordered = sorted(unique.values(), key=lambda p: p.timestamp)
    return ordered[-params.limit :]
