from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import SessionDep, require_role
from app.db.session import engine
from app.models import Role, User
from app.schemas.admin import (
    DbStatus,
    LogParams,
    MetricHistoryParams,
    MetricRead,
    PageParams,
    SystemLogRead,
    UserUpdate,
)
from app.schemas.common import Page
from app.schemas.user import UserRead
from app.services import admin_service

# 同一個 dependency 物件：router 層級與端點參數共用，FastAPI 在同一請求內只執行一次
require_admin = require_role(Role.ADMIN)
AdminUser = Annotated[User, Depends(require_admin)]

# router 層級 dependency：所有 admin 端點都先檢查角色，新增端點時不會漏加
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/users", response_model=Page[UserRead])
async def list_users(params: Annotated[PageParams, Query()], session: SessionDep) -> Page[UserRead]:
    items, total = await admin_service.list_users(session, params)
    return Page[UserRead](
        items=[UserRead.model_validate(u) for u in items],
        total=total,
        page=params.page,
        size=params.size,
    )


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int, payload: UserUpdate, session: SessionDep, admin: AdminUser
) -> User:
    """修改角色或啟用狀態，立即生效（JWT 不含角色，每次請求從 DB 讀）。不可修改自己。"""
    return await admin_service.update_user(session, user_id, payload, actor=admin)


@router.get("/logs", response_model=Page[SystemLogRead])
async def list_logs(
    params: Annotated[LogParams, Query()], session: SessionDep
) -> Page[SystemLogRead]:
    items, total = await admin_service.list_logs(session, params)
    return Page[SystemLogRead](
        items=[SystemLogRead.model_validate(log) for log in items],
        total=total,
        page=params.page,
        size=params.size,
    )


@router.get("/db-status", response_model=DbStatus)
async def db_status(request: Request, session: SessionDep) -> DbStatus:
    """DB 連線與延遲、連接池、各表筆數、即時資料 buffer 待寫筆數、WebSocket 連線數。"""
    return await admin_service.db_status(
        session,
        engine,
        request.app.state.metric_buffer,
        request.app.state.ws_manager.count,
    )


@router.get("/metrics", response_model=Page[MetricRead])
async def list_metrics(
    params: Annotated[MetricHistoryParams, Query()], session: SessionDep
) -> Page[MetricRead]:
    items, total = await admin_service.list_metrics(session, params)
    return Page[MetricRead](
        items=[MetricRead.model_validate(m) for m in items],
        total=total,
        page=params.page,
        size=params.size,
    )
