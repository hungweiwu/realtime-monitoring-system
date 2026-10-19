from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Record, Role, User
from app.schemas.record import RecordCreate, RecordPatch, RecordPut
from app.services.log_service import log_action


async def create(session: AsyncSession, data: RecordCreate, actor: User) -> Record:
    record = Record(**data.model_dump(), created_by=actor.id)
    session.add(record)
    await session.flush()
    log_action(session, "record.create", user_id=actor.id, detail=f"id={record.id}")
    await session.commit()
    return record


async def get(session: AsyncSession, record_id: int) -> Record:
    record = await session.get(Record, record_id)
    if record is None:
        raise NotFoundError("record", record_id)
    return record


async def _get_modifiable(session: AsyncSession, record_id: int, actor: User) -> Record:
    record = await get(session, record_id)
    # 建立者檢查需要先讀出資料，所以放在 service 而非 dependency
    if actor.role != Role.ADMIN and record.created_by != actor.id:
        raise PermissionDeniedError("only the creator or an admin can modify this record")
    return record


async def update(
    session: AsyncSession, record_id: int, data: RecordPut | RecordPatch, actor: User
) -> Record:
    record = await _get_modifiable(session, record_id, actor)
    # PUT 的 schema 全欄位必填，exclude_unset 對它等同全部更新；PATCH 只更新有帶的欄位
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(record, field, value)
    log_action(
        session,
        "record.update",
        user_id=actor.id,
        detail=f"id={record_id} fields={sorted(changes)}",
    )
    await session.commit()
    return record


async def delete(session: AsyncSession, record_id: int, actor: User) -> None:
    record = await _get_modifiable(session, record_id, actor)
    await session.delete(record)
    log_action(session, "record.delete", user_id=actor.id, detail=f"id={record_id}")
    await session.commit()
