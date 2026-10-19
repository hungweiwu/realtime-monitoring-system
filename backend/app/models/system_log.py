from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class SystemLog(Base):
    __tablename__ = "system_logs"
    __table_args__ = (Index("ix_system_logs_level_created_at", "level", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(50))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
