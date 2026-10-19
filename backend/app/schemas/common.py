from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# 回應用：剛寫入的物件仍帶使用者輸入的時區，從 DB 讀出的則是 UTC；統一轉 UTC 讓輸出一致
UTCDatetimeOut = Annotated[AwareDatetime, AfterValidator(_to_utc)]
