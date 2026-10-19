from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, UploadFile, status

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep, require_role
from app.models import Record, Role, User
from app.schemas.common import Page
from app.schemas.record import (
    ImportResult,
    RecordCreate,
    RecordListParams,
    RecordPatch,
    RecordPut,
    RecordRead,
)
from app.services import import_service, record_service

router = APIRouter(prefix="/records", tags=["records"])

Writer = Annotated[User, Depends(require_role(Role.ADMIN, Role.USER))]


@router.post("", response_model=RecordRead, status_code=status.HTTP_201_CREATED)
async def create_record(payload: RecordCreate, session: SessionDep, user: Writer) -> Record:
    return await record_service.create(session, payload, actor=user)


@router.post("/import", response_model=ImportResult)
async def import_records(file: UploadFile, session: SessionDep, user: Writer) -> ImportResult:
    """上傳 CSV 或 JSON 批量匯入。合格列寫入、不合格列回報（部分成功）。"""
    # 多讀 1 byte 即可判斷是否超過上限，超出部分不會讀進 Python 記憶體。
    # 注意 Starlette 在 handler 執行前已收完整個上傳（大檔暫存磁碟），這裡擋不住頻寬與磁碟用量
    raw = await file.read(get_settings().import_max_bytes + 1)
    return await import_service.import_records(session, file.filename or "", raw, actor=user)


@router.get("", response_model=Page[RecordRead])
async def list_records(
    params: Annotated[RecordListParams, Query()], session: SessionDep, user: CurrentUser
) -> Page[RecordRead]:
    items, total = await record_service.list_records(session, params)
    return Page[RecordRead](
        items=[RecordRead.model_validate(r) for r in items],
        total=total,
        page=params.page,
        size=params.size,
    )


@router.get("/{record_id}", response_model=RecordRead)
async def get_record(record_id: int, session: SessionDep, user: CurrentUser) -> Record:
    return await record_service.get(session, record_id)


@router.put("/{record_id}", response_model=RecordRead)
async def replace_record(
    record_id: int, payload: RecordPut, session: SessionDep, user: Writer
) -> Record:
    return await record_service.update(session, record_id, payload, actor=user)


@router.patch("/{record_id}", response_model=RecordRead)
async def patch_record(
    record_id: int, payload: RecordPatch, session: SessionDep, user: Writer
) -> Record:
    return await record_service.update(session, record_id, payload, actor=user)


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(record_id: int, session: SessionDep, user: Writer) -> Response:
    await record_service.delete(session, record_id, actor=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
