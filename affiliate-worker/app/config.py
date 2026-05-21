from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr | None = Field(default=None, alias="DATABASE_URL")
    affiliate_import_mode: str = Field(default="production", alias="AFFILIATE_IMPORT_MODE")
    affiliate_log_level: str = Field(default="INFO", alias="AFFILIATE_LOG_LEVEL")
    affiliate_data_dir: Path = Field(default=Path("/data"), alias="AFFILIATE_DATA_DIR")
    affiliate_deactivate_after_missed_imports: int = Field(
        default=3,
        alias="AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS",
    )
    affiliate_match_auto_threshold: int = Field(
        default=95,
        alias="AFFILIATE_MATCH_AUTO_THRESHOLD",
    )
    affiliate_match_review_threshold: int = Field(
        default=85,
        alias="AFFILIATE_MATCH_REVIEW_THRESHOLD",
    )
    awin_publisher_id: str | None = Field(default=None, alias="AWIN_PUBLISHER_ID")
    awin_api_token: SecretStr | None = Field(default=None, alias="AWIN_API_TOKEN")
    awin_product_feed_api_key: SecretStr | None = Field(
        default=None,
        alias="AWIN_PRODUCT_FEED_API_KEY",
    )

    @staticmethod
    def _is_secret_configured(value: SecretStr | None) -> bool:
        return value is not None and bool(value.get_secret_value())

    def safe_dict(self) -> dict[str, object]:
        data_dir = self.affiliate_data_dir
        return {
            "affiliate_import_mode": self.affiliate_import_mode,
            "affiliate_log_level": self.affiliate_log_level,
            "affiliate_data_dir": str(data_dir),
            "feeds_dir": str(data_dir / "feeds"),
            "reports_dir": str(data_dir / "reports"),
            "logs_dir": str(data_dir / "logs"),
            "affiliate_deactivate_after_missed_imports": (
                self.affiliate_deactivate_after_missed_imports
            ),
            "affiliate_match_auto_threshold": self.affiliate_match_auto_threshold,
            "affiliate_match_review_threshold": self.affiliate_match_review_threshold,
            "database_url_configured": self._is_secret_configured(self.database_url),
            "awin_publisher_id_configured": bool(self.awin_publisher_id),
            "awin_api_token_configured": self._is_secret_configured(self.awin_api_token),
            "awin_product_feed_api_key_configured": self._is_secret_configured(
                self.awin_product_feed_api_key
            ),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
