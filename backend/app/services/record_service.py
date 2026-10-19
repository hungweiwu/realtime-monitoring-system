from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Record, Role, User
from app.schemas.record import RecordCreate, RecordListParams, RecordPatch, RecordPut
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


SORT_COLUMNS = {
    "timestamp": Record.timestamp,
    "value": Record.value,
    "created_at": Record.created_at,
    "title": Record.title,
}


async def list_records(session: AsyncSession, params: RecordListParams) -> tuple[list[Record], int]:
    conditions = []
    if params.category is not None:
        conditions.append(Record.category == params.category)
    if params.start is not None:
        conditions.append(Record.timestamp >= params.start)
    if params.end is not None:
        conditions.append(Record.timestamp <= params.end)
    if params.min_value is not None:
        conditions.append(Record.value >= params.min_value)
    if params.max_value is not None:
        conditions.append(Record.value <= params.max_value)

    total = await session.scalar(select(func.count()).select_from(Record).where(*conditions))

    column = SORT_COLUMNS[params.sort_by]
    primary = column.asc() if params.order == "asc" else column.desc()
    stmt = (
        select(Record)
        .where(*conditions)
        # 加 id 作為次要排序：排序值相同時 MariaDB 不保證順序，分頁會重複或漏資料
        .order_by(primary, Record.id.asc() if params.order == "asc" else Record.id.desc())
        .offset((params.page - 1) * params.size)
        .limit(params.size)
    )
    items = (await session.scalars(stmt)).all()
    return list(items), total or 0


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
