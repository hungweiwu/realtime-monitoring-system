from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# 允許的時間範圍（UTC）。下限 1970：MariaDB CONVERT_TZ 對 1970 以前不轉換，趨勢分桶會錯位；
# 上限 2100：避免極端值。範圍外的時間在 API 邊界回 422，不讓它走到 DB 層溢位變成 500
MIN_TIMESTAMP = datetime(1970, 1, 1, tzinfo=UTC)
MAX_TIMESTAMP = datetime(2100, 1, 1, tzinfo=UTC)


def ensure_in_range(value: datetime) -> datetime:
    """檢查帶時區的時間落在允許範圍，回傳 UTC。

    先看年份再轉 UTC：西元 1 年帶 +08:00 這類值在 astimezone() 時就會 OverflowError。
    """
    if not MIN_TIMESTAMP.year - 1 <= value.year <= MAX_TIMESTAMP.year:
        raise ValueError("timestamp must be between 1970-01-01 and 2100-01-01 (UTC)")
    utc = value.astimezone(UTC)
    if not MIN_TIMESTAMP <= utc < MAX_TIMESTAMP:
        raise ValueError("timestamp must be between 1970-01-01 and 2100-01-01 (UTC)")
    return utc


# 請求用：必須帶時區（否則 422）且在允許範圍內；驗證後統一為 UTC
BoundedDatetime = Annotated[AwareDatetime, AfterValidator(ensure_in_range)]


# 回應用：剛寫入的物件仍帶使用者輸入的時區，從 DB 讀出的則是 UTC；統一轉 UTC 讓輸出一致
UTCDatetimeOut = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int
