import logging.config


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
