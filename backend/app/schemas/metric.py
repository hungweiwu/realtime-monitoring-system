from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UTCDatetimeOut


class MetricPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: float
    category: str
    timestamp: UTCDatetimeOut
    is_anomaly: bool


class LatestParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(60, ge=1, le=500)
