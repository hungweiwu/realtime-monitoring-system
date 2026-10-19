import asyncio
import io
import unicodedata
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter
from openpyxl.worksheet._write_only import WriteOnlyWorksheet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.schemas.analytics import AnalyticsParams, CategoryStat, Summary
from app.services import analytics_service
from app.services.analytics_service import MODELS, analytics_timezone, conditions

MIN_COLUMN_WIDTH = 8
MAX_COLUMN_WIDTH = 50  # 超長 title 不把欄位撐到幾百字寬

COLUMNS = {
    "records": ["id", "title", "value", "category", "timestamp", "created_by"],
    "metrics": ["value", "category", "timestamp", "is_anomaly"],
}


def _cell(ws: WriteOnlyWorksheet, value: Any, tz: ZoneInfo) -> Any:
    if isinstance(value, datetime):
        # Excel 不支援帶時區的時間：轉成分析時區後去掉 tzinfo，欄位標題註明時區
        return value.astimezone(tz).replace(tzinfo=None)
    if isinstance(value, str):
        # 強制存成文字：openpyxl 會把 "=" 開頭的字串寫成公式，
        # 使用者匯入的 title 若是 =HYPERLINK(...) 等，打開檔案時就會被執行（公式注入）
        cell = WriteOnlyCell(ws, value=value)
        cell.data_type = "s"
        return cell
    return value


async def build_workbook(session: AsyncSession, params: AnalyticsParams) -> bytes:
    settings = get_settings()
    model = MODELS[params.source]
    columns = COLUMNS[params.source]
    tz = analytics_timezone()

    # 超過上限時保留最新的資料：先依時間倒序取，再反轉成由舊到新
    stmt = (
        select(*(getattr(model, c) for c in columns))
        .where(*conditions(model, params))
        .order_by(model.timestamp.desc(), model.id.desc())
        .limit(settings.export_max_rows)
    )
    rows = list(reversed((await session.execute(stmt)).all()))
    summary = await analytics_service.summary(session, params)
    categories = await analytics_service.by_category(session, params)

    # 產生 xlsx 是純 CPU 工作（5 萬列需數秒）：放到執行緒，避免卡住 event loop 上的產生器與推送
    return await asyncio.to_thread(_render_workbook, params, columns, rows, summary, categories, tz)


def _display_width(value: Any) -> int:
    """估計儲存格在 Excel 中顯示所需的字寬。"""
    if value is None:
        return 0
    if isinstance(value, datetime):
        return len("2026-10-20 08:00:00")
    if isinstance(value, float):
        # Excel「通用」格式最多顯示約 11 位數，不會把 33.187000000000005 全部印出
        return min(len(f"{value:.10g}"), 12)
    # 全形字（中日韓）約佔兩個字寬
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(value))


def _set_column_widths(ws: WriteOnlyWorksheet, rows: Sequence[Sequence[Any]]) -> None:
    # write-only 工作表只能在寫入任何一列之前設定欄寬
    widths: dict[int, int] = {}
    for row in rows:
        for index, value in enumerate(row, start=1):
            widths[index] = max(widths.get(index, 0), _display_width(value))
    for index, width in widths.items():
        ws.column_dimensions[get_column_letter(index)].width = min(
            max(width + 2, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH
        )


def _render_workbook(
    params: AnalyticsParams,
    columns: list[str],
    rows: Sequence[Sequence[Any]],
    summary: Summary,
    categories: list[CategoryStat],
    tz: ZoneInfo,
) -> bytes:
    # write_only：逐列寫入不在記憶體保留整份工作表物件，大量資料時記憶體用量較低
    wb = Workbook(write_only=True)
    data = wb.create_sheet("data")
    header = [f"timestamp ({tz.key})" if c == "timestamp" else c for c in columns]
    _set_column_widths(data, [header, *rows])
    data.append(header)
    for row in rows:
        data.append([_cell(data, v, tz) for v in row])

    summary_rows: list[list[Any]] = [
        ["source", params.source],
        ["category", params.category or "(all)"],
        ["start", params.start or "(none)"],
        ["end", params.end or "(none)"],
        ["exported_rows", len(rows)],
        *([key, getattr(summary, key)] for key in ("count", "sum", "avg", "max", "min")),
        [],
        ["by category", "count", "avg", "max", "min"],
        *([stat.category, stat.count, stat.avg, stat.max, stat.min] for stat in categories),
    ]
    sheet = wb.create_sheet("summary")
    _set_column_widths(sheet, summary_rows)
    for row in summary_rows:
        sheet.append([_cell(sheet, v, tz) for v in row])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
