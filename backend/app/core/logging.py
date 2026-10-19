import logging
import logging.config
import re

_TOKEN_PATTERN = re.compile(r"(token=)[^&\s\"]+")


class TokenRedactingFilter(logging.Filter):
    """遮蔽 log 中的 token query 參數。

    瀏覽器 WebSocket 無法帶 header，JWT 只能放 query string；uvicorn 會把完整路徑寫進 log
    （WebSocket 握手記在 uvicorn.error，HTTP 記在 uvicorn.access），不遮蔽 token 就會外洩到日誌。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "token=" in message:
            record.msg = _TOKEN_PATTERN.sub(r"\1***", message)
            record.args = None
        return True


def setup_logging(level: str) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            # 保留 uvicorn 自己設定好的 logger
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                },
            },
            "loggers": {
                "app": {"handlers": ["stdout"], "level": level, "propagate": False},
            },
        }
    )
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(TokenRedactingFilter())
