from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.deps import CurrentUser, SessionDep
from app.schemas.analytics import (
    AnalyticsParams,
    CategoryStat,
    Summary,
    TrendParams,
    TrendPoint,
)
from app.services import analytics_service, export_service

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


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}, "description": "Excel 檔案"}},
)
async def export(
    params: Annotated[AnalyticsParams, Query()], session: SessionDep, user: CurrentUser
) -> Response:
    """下載 .xlsx：`data` 工作表（套用相同篩選，上限 5 萬列、保留最新）＋ `summary` 統計。"""
    content = await export_service.build_workbook(session, params)
    # 檔名時間與檔案內容一致，用分析時區
    filename = (
        f"{params.source}_{datetime.now(analytics_service.analytics_timezone()):%Y%m%d_%H%M%S}.xlsx"
    )
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
