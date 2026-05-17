from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    database_url: str | None
    import_mode: str
    log_level: str
    data_dir: Path
    deactivate_after_missed_imports: int
    match_auto_threshold: float
    match_review_threshold: float
    awin_publisher_id: str | None
    awin_api_token: str | None
    awin_product_feed_api_key: str | None

    @property
    def feeds_dir(self) -> Path:
        return self.data_dir / "feeds"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_data_dirs(self) -> None:
        self.feeds_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


def _get_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc


def _get_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number") from exc


def _get_optional(name: str) -> str | None:
    value = os.getenv(name)
    return value if value else None


def load_settings() -> Settings:
    """Load worker settings from environment variables.

    This skeleton intentionally does not validate DB or Awin credentials yet.
    Later PRs will validate required credentials per command.
    """

    data_dir = Path(os.getenv("AFFILIATE_DATA_DIR", "/data")).expanduser()

    return Settings(
        database_url=_get_optional("DATABASE_URL"),
        import_mode=os.getenv("AFFILIATE_IMPORT_MODE", "development"),
        log_level=os.getenv("AFFILIATE_LOG_LEVEL", "INFO"),
        data_dir=data_dir,
        deactivate_after_missed_imports=_get_int(
            "AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS",
            3,
        ),
        match_auto_threshold=_get_float("AFFILIATE_MATCH_AUTO_THRESHOLD", 95.0),
        match_review_threshold=_get_float("AFFILIATE_MATCH_REVIEW_THRESHOLD", 85.0),
        awin_publisher_id=_get_optional("AWIN_PUBLISHER_ID"),
        awin_api_token=_get_optional("AWIN_API_TOKEN"),
        awin_product_feed_api_key=_get_optional("AWIN_PRODUCT_FEED_API_KEY"),
    )
