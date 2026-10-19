from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep
from app.schemas.analytics import (
    AnalyticsParams,
    CategoryStat,
    Summary,
    TrendParams,
    TrendPoint,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=Summary)
async def summary(
    params: Annotated[AnalyticsParams, Query()], session: SessionDep, user: CurrentUser
) -> Summary:
    """總筆數、總和、平均、最大、最小。`source` 選擇 records 或 metrics（預設）。"""
    return await analytics_service.summary(session, params)


@router.get("/by-category", response_model=list[CategoryStat])
async def by_category(
    params: Annotated[AnalyticsParams, Query()], session: SessionDep, user: CurrentUser
) -> list[CategoryStat]:
    return await analytics_service.by_category(session, params)


@router.get("/trend", response_model=list[TrendPoint])
async def trend(
    params: Annotated[TrendParams, Query()], session: SessionDep, user: CurrentUser
) -> list[TrendPoint]:
    """依 minute / hour / day 分組（以台北時間切分），bucket 為區間起點（UTC）。"""
    return await analytics_service.trend(session, params)
