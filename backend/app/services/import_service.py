import csv
import io
import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import PayloadTooLargeError, UnprocessableError
from app.models import Record, User
from app.schemas.record import ImportResult, ImportRowError, RecordImportRow
from app.services.log_service import log_action

REQUIRED_COLUMNS = {"title", "value", "category", "timestamp"}


def _parse_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    try:
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise UnprocessableError(
                f"CSV is missing required columns: {', '.join(sorted(missing))}"
            )
        return list(reader)
    except csv.Error as exc:
        # 例如單一欄位超過 csv 模組上限（預設 131072 字元）
        raise UnprocessableError(f"invalid CSV: {exc}") from None


def _parse_json(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UnprocessableError(f"invalid JSON: {exc.msg}") from None
    except RecursionError:
        # 深層巢狀（[[[[...）會讓解析器遞迴過深
        raise UnprocessableError("invalid JSON: nesting too deep") from None
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise UnprocessableError("JSON must be an array of objects")
    return data


def _format_errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'row'}: {err['msg']}" for err in exc.errors()
    )


def parse_rows(filename: str, raw: bytes) -> list[dict[str, Any]]:
    settings = get_settings()
    if len(raw) > settings.import_max_bytes:
        raise PayloadTooLargeError(f"file exceeds {settings.import_max_bytes} bytes")

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ("csv", "json"):
        raise UnprocessableError("only .csv and .json files are supported")
    try:
        # utf-8-sig 會去掉 Excel 另存 CSV 時加的 BOM
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UnprocessableError("file must be UTF-8 encoded") from None

    rows = _parse_csv(text) if suffix == "csv" else _parse_json(text)
    if len(rows) > settings.import_max_rows:
        raise PayloadTooLargeError(f"file exceeds {settings.import_max_rows} rows")
    return rows


async def import_records(
    session: AsyncSession, filename: str, raw: bytes, actor: User
) -> ImportResult:
    rows = parse_rows(filename, raw)
    records: list[Record] = []
    errors: list[ImportRowError] = []
    # row 為資料列序號（從 1 起算，不含 CSV 標題列）
    for index, raw_row in enumerate(rows, start=1):
        try:
            row = RecordImportRow.model_validate(raw_row)
        except ValidationError as exc:
            errors.append(ImportRowError(row=index, message=_format_errors(exc)))
            continue
        records.append(
            Record(
                title=row.title,
                value=row.value,
                category=row.category,
                timestamp=row.timestamp,
                created_by=actor.id,
            )
        )

    # 合格列一次寫入（部分成功）；整批同一個 transaction，寫入失敗不會留下半批資料
    session.add_all(records)
    log_action(
        session,
        "record.import",
        user_id=actor.id,
        detail=f"file={filename} success={len(records)} failed={len(errors)}",
    )
    await session.commit()
    return ImportResult(success_count=len(records), failed_count=len(errors), errors=errors)
