from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.core.deps import CurrentUser, SessionDep
from app.schemas.metric import LatestParams, MetricPointOut
from app.services import metric_service

router = APIRouter(prefix="/metrics", tags=["realtime"])


@router.get("/latest", response_model=list[MetricPointOut])
async def latest_metrics(
    params: Annotated[LatestParams, Query()],
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> list[MetricPointOut]:
    """最新 N 筆即時資料（時間由舊到新），包含尚未寫入 DB 的 buffer 資料。"""
    return await metric_service.latest(session, request.app.state.metric_buffer, params.limit)
