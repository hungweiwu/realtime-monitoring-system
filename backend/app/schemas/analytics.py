from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from app.schemas.common import UTCDatetimeOut

Source = Literal["records", "metrics"]


class AnalyticsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source = "metrics"
    category: str | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class TrendParams(AnalyticsParams):
    interval: Literal["minute", "hour", "day"] = "hour"


class Summary(BaseModel):
    count: int
    sum: float | None
    avg: float | None
    max: float | None
    min: float | None


class CategoryStat(BaseModel):
    category: str
    count: int
    avg: float
    max: float
    min: float


class TrendPoint(BaseModel):
    bucket: UTCDatetimeOut
    count: int
    avg: float
    max: float
    min: float
