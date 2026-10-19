from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "monitor"
    db_password: str = "monitorpass"
    db_name: str = "monitor"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800
    # 測試時改用 NullPool：pytest-asyncio 每個測試各有 event loop，
    # 池中連線會綁在舊 loop 上而出錯
    db_use_null_pool: bool = False

    log_level: str = "INFO"

    jwt_secret_key: str = "dev-only-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    import_max_bytes: int = 5 * 1024 * 1024
    import_max_rows: int = 10_000
    # 匯入資料的時間若沒帶時區，視為此時區
    import_default_timezone: str = "Asia/Taipei"

    # 即時資料產生器與批次寫入
    enable_generator: bool = True
    metric_interval_seconds: float = 1.0
    metric_anomaly_low: float = 10.0
    metric_anomaly_high: float = 90.0
    flush_interval_seconds: float = 5.0
    flush_batch_size: int = 50
    # DB 長時間寫不進去時 buffer 的上限，超過丟最舊的，避免記憶體無限成長
    buffer_max_size: int = 10_000
    # 單一 WebSocket 連線送一筆資料的逾時，超過視為慢連線並斷開
    ws_send_timeout_seconds: float = 1.0

    # 趨勢分析切分「分 / 時 / 日」與 Excel 匯出時間所用的時區
    analytics_timezone: str = "Asia/Taipei"
    # Excel 匯出的 data 工作表列數上限，超過時保留最新的資料
    export_max_rows: int = 50_000

    # 種子帳號：啟動時若不存在就建立，README 列出供審查者測試
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin12345"
    seed_user_username: str = "user"
    seed_user_password: str = "user12345"
    seed_viewer_username: str = "viewer"
    seed_viewer_password: str = "viewer12345"

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
