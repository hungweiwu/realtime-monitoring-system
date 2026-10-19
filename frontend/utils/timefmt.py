"""前端時間一律以 Asia/Taipei 顯示與輸入；API 進出都是帶時區的 ISO 8601。"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("Asia/Taipei")
TZ_LABEL = "台北時間"


def to_local(iso: str) -> datetime:
    """API 回傳的 UTC 字串轉台北時間（去掉 tzinfo 方便表格與圖表顯示）。"""
    return datetime.fromisoformat(iso).astimezone(TZ).replace(tzinfo=None)


def to_api(d: date, t: time = time(0, 0)) -> str:
    """使用者輸入的台北日期時間轉成帶時區的 ISO 字串（API 拒收沒帶時區的時間）。"""
    return datetime.combine(d, t, tzinfo=TZ).isoformat()


def localize_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if column in df:
        df[column] = df[column].map(to_local)
    return df
