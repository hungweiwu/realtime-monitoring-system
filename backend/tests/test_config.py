import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_log_level_is_case_insensitive() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="verbose")


@pytest.mark.parametrize(
    "overrides",
    [
        {"metric_interval_seconds": 0},
        {"flush_batch_size": 0},
        {"flush_interval_seconds": -1},
        {"buffer_max_size": 10, "flush_batch_size": 50},
        {"metric_anomaly_low": 90, "metric_anomaly_high": 10},
        {"access_token_expire_minutes": 0},
        {"db_pool_size": 0},
        {"analytics_timezone": "Not/AZone"},
    ],
)
def test_invalid_numeric_or_timezone_settings_fail_fast(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)
