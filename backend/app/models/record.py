from datetime import datetime

from sqlalchemy import Double, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (Index("ix_records_category_timestamp", "category", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    value: Mapped[float] = mapped_column(Double)
    category: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
