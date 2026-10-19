from functools import lru_cache
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# 開發用預設值：讓 docker compose up 不需 .env 就能啟動。任何人都能用它簽出 Admin token，
# 正式環境必須以環境變數覆寫（啟動時若仍是此值會印出警告）
DEV_JWT_SECRET = "dev-only-change-me-in-production-0123456789"


def _valid_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown timezone: {name}") from None
    return name


Timezone = Annotated[str, AfterValidator(_valid_timezone)]
Positive = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class Settings(BaseSettings):
    """所有設定皆在啟動時驗證：錯誤值（0、負數、未知時區）讓服務直接起不來，
    而不是靜默變成忙迴圈或失效的門檻。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "localhost"
    db_port: Annotated[int, Field(ge=1, le=65535)] = 3306
    db_user: str = "monitor"
    db_password: str = "monitorpass"
    db_name: str = "monitor"
    db_pool_size: PositiveInt = 5
    db_max_overflow: Annotated[int, Field(ge=0)] = 10
    db_pool_recycle_seconds: PositiveInt = 1800
    # 測試時改用 NullPool：pytest-asyncio 每個測試各有 event loop，
    # 池中連線會綁在舊 loop 上而出錯
    db_use_null_pool: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: PositiveInt = 60

    import_max_bytes: PositiveInt = 5 * 1024 * 1024
    import_max_rows: PositiveInt = 10_000
    # 匯入資料的時間若沒帶時區，視為此時區
    import_default_timezone: Timezone = "Asia/Taipei"

    # 即時資料產生器與批次寫入
    enable_generator: bool = True
    metric_interval_seconds: Positive = 1.0
    metric_anomaly_low: float = 10.0
    metric_anomaly_high: float = 90.0
    flush_interval_seconds: Positive = 5.0
    flush_batch_size: PositiveInt = 50
    # DB 長時間寫不進去時 buffer 的上限，超過丟最舊的，避免記憶體無限成長
    buffer_max_size: PositiveInt = 10_000
    # 單一 WebSocket 連線送一筆資料的逾時，超過視為慢連線並斷開
    ws_send_timeout_seconds: Positive = 1.0

    # 趨勢分析切分「分 / 時 / 日」與 Excel 匯出時間所用的時區
    analytics_timezone: Timezone = "Asia/Taipei"
    # Excel 匯出的 data 工作表列數上限，超過時保留最新的資料
    export_max_rows: PositiveInt = 50_000

    # 種子帳號：啟動時若不存在就建立，README 列出供審查者測試
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin12345"
    seed_user_username: str = "user"
    seed_user_password: str = "user12345"
    seed_viewer_username: str = "viewer"
    seed_viewer_password: str = "viewer12345"

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        # LOG_LEVEL=debug 也接受；否則 logging.dictConfig 會在啟動時直接失敗
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def check_relations(self) -> Self:
        if self.buffer_max_size < self.flush_batch_size:
            raise ValueError(
                "buffer_max_size must be >= flush_batch_size, or no flush is triggered"
            )
        if self.metric_anomaly_low >= self.metric_anomaly_high:
            raise ValueError("metric_anomaly_low must be lower than metric_anomaly_high")
        return self

    @property
    def database_url(self) -> URL:
        # URL.create 會處理密碼中的特殊字元，字串拼接遇到 @ 或 / 會壞掉
        return URL.create(
            "mysql+asyncmy",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
