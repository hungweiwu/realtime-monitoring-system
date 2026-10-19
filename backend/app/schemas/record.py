from datetime import datetime
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

from app.core.config import get_settings
from app.schemas.common import BoundedDatetime, UTCDatetimeOut, ensure_in_range

Title = Annotated[str, Field(min_length=1, max_length=200)]
Category = Annotated[str, Field(min_length=1, max_length=50)]


class RecordCreate(BaseModel):
    # extra="forbid"：擋下 created_by 等不該由使用者指定的欄位
    model_config = ConfigDict(extra="forbid")

    title: Title
    # FiniteFloat 擋掉 NaN / Infinity，MariaDB DOUBLE 存不了
    value: FiniteFloat
    category: Category
    # 沒帶時區或超出範圍直接 422，不讓 naive／極端時間走到 DB 層變成 500
    timestamp: BoundedDatetime


class RecordPut(RecordCreate):
    """PUT 為整筆取代，欄位與新增相同且全部必填。"""


class RecordPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    value: FiniteFloat | None = None
    category: Category | None = None
    timestamp: BoundedDatetime | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, data: Any) -> Any:
        # 欄位可省略，但不能明確傳 null：DB 欄位皆為 NOT NULL
        if isinstance(data, dict):
            nulls = [key for key, value in data.items() if value is None]
            if nulls:
                raise ValueError(f"fields cannot be null: {', '.join(nulls)}")
        return data


class RecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    value: float
    category: str
    timestamp: UTCDatetimeOut
    created_by: int
    created_at: UTCDatetimeOut
    updated_at: UTCDatetimeOut


class RecordListParams(BaseModel):
    # extra="forbid"：拼錯的 query 參數（例如 sortby）直接 422，而不是被默默忽略
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    category: str | None = None
    start: BoundedDatetime | None = None
    end: BoundedDatetime | None = None
    min_value: float | None = None
    max_value: float | None = None
    # 白名單：只允許這些欄位排序，不接受任意欄位名
    sort_by: Literal["timestamp", "value", "created_at", "title"] = "timestamp"
    order: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must not be after end")
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("min_value must not be greater than max_value")
        return self


class RecordImportRow(BaseModel):
    """匯入檔案的單列。與 RecordCreate 不同：允許沒帶時區的時間（由 import_service 補時區），
    並忽略多餘欄位（使用者匯出的檔案常帶 id 等欄位）。"""

    model_config = ConfigDict(extra="ignore")

    title: Title
    value: FiniteFloat
    category: Category
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def localize_and_check_range(cls, value: datetime) -> datetime:
        # 沒帶時區視為匯入預設時區（Asia/Taipei）；範圍外的列在這裡失敗，
        # 會被記成該列的錯誤，而不是整批寫入時在 DB 層 500
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(get_settings().import_default_timezone))
        return ensure_in_range(value)


class ImportRowError(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    success_count: int
    failed_count: int
    errors: list[ImportRowError]
