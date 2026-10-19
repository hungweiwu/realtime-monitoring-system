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
