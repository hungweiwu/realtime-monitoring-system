from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.deps import CurrentUser, SessionDep, require_role
from app.models import Record, Role, User
from app.schemas.record import RecordCreate, RecordPatch, RecordPut, RecordRead
from app.services import record_service

router = APIRouter(prefix="/records", tags=["records"])

Writer = Annotated[User, Depends(require_role(Role.ADMIN, Role.USER))]


@router.post("", response_model=RecordRead, status_code=status.HTTP_201_CREATED)
async def create_record(payload: RecordCreate, session: SessionDep, user: Writer) -> Record:
    return await record_service.create(session, payload, actor=user)


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
