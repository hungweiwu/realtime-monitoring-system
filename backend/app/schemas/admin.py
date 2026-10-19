from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import Role
from app.schemas.common import BoundedDatetime, UTCDatetimeOut


class PageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)


class TimeRangeParams(PageParams):
    start: BoundedDatetime | None = None
    end: BoundedDatetime | None = None

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulls = [key for key, value in data.items() if value is None]
            if nulls:
                raise ValueError(f"fields cannot be null: {', '.join(nulls)}")
        return data


class LogParams(TimeRangeParams):
    level: str | None = None
    action: str | None = None


class SystemLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    action: str
    user_id: int | None
    detail: str | None
    created_at: UTCDatetimeOut


class MetricHistoryParams(TimeRangeParams):
    anomaly_only: bool = False
    category: str | None = None


class MetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    value: float
    category: str
    timestamp: UTCDatetimeOut
    is_anomaly: bool


class DatabaseCheck(BaseModel):
    ok: bool
    latency_ms: float | None


class DbStatus(BaseModel):
    database: DatabaseCheck
    # 連接池狀態；測試環境使用 NullPool 時沒有這些數字
    pool: dict[str, int | str]
    tables: dict[str, int]
    buffer: dict[str, int]
    websocket_connections: int
