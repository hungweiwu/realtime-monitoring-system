from datetime import datetime

from sqlalchemy import Boolean, Double, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (Index("ix_metrics_is_anomaly_timestamp", "is_anomaly", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[float] = mapped_column(Double)
    category: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
