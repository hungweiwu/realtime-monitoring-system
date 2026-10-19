from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from app.schemas.common import UTCDatetimeOut

Title = Annotated[str, Field(min_length=1, max_length=200)]
Category = Annotated[str, Field(min_length=1, max_length=50)]


class RecordCreate(BaseModel):
    # extra="forbid"：擋下 created_by 等不該由使用者指定的欄位
    model_config = ConfigDict(extra="forbid")

    title: Title
    # FiniteFloat 擋掉 NaN / Infinity，MariaDB DOUBLE 存不了
    value: FiniteFloat
    category: Category
    # AwareDatetime：沒帶時區直接 422，不讓 naive datetime 走到 DB 層變成 500
    timestamp: AwareDatetime


class RecordPut(RecordCreate):
    """PUT 為整筆取代，欄位與新增相同且全部必填。"""


class RecordPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    value: FiniteFloat | None = None
    category: Category | None = None
    timestamp: AwareDatetime | None = None

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
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
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
