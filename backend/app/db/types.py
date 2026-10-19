from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """MariaDB DATETIME 不存時區：寫入時統一轉 UTC 去掉 tzinfo，讀出時補回 UTC。

    應用程式其他地方因此只會碰到 aware datetime；拒收 naive datetime，
    避免本地時間被默默當成 UTC 寫入。
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[datetime]:
        if dialect.name in ("mysql", "mariadb"):
            # fsp=6 保留微秒，每秒產生的即時資料排序才穩定
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed; attach a timezone first")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)
