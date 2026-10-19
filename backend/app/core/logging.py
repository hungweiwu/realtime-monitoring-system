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
        # 在 args 內逐項遮蔽而非改寫成單一字串：uvicorn 的 AccessFormatter 會把 args 解包成
        # 固定 5 個值，args 被清掉會讓整行 access log 格式化失敗而遺失
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        return True


def _redact(text: str) -> str:
    return _TOKEN_PATTERN.sub(r"\1***", text) if "token=" in text else text


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
