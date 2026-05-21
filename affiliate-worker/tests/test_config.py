from __future__ import annotations

from pathlib import Path

from app.config import Settings


def test_settings_defaults(monkeypatch) -> None:
    env_keys = [
        "DATABASE_URL",
        "AFFILIATE_IMPORT_MODE",
        "AFFILIATE_LOG_LEVEL",
        "AFFILIATE_DATA_DIR",
        "AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS",
        "AFFILIATE_MATCH_AUTO_THRESHOLD",
        "AFFILIATE_MATCH_REVIEW_THRESHOLD",
        "AWIN_PUBLISHER_ID",
        "AWIN_API_TOKEN",
        "AWIN_PRODUCT_FEED_API_KEY",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)

    settings = Settings()

    assert settings.affiliate_import_mode == "production"
    assert settings.affiliate_log_level == "INFO"
    assert settings.affiliate_data_dir == Path("/data")
    assert settings.affiliate_deactivate_after_missed_imports == 3
    assert settings.affiliate_match_auto_threshold == 95
    assert settings.affiliate_match_review_threshold == 85
    assert settings.database_url is None


def test_safe_dict_reports_configuration_without_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@db:5432/mes_fragrances")
    monkeypatch.setenv("AFFILIATE_DATA_DIR", "/srv/affiliate-data")
    monkeypatch.setenv("AWIN_PUBLISHER_ID", "pub-1")
    monkeypatch.setenv("AWIN_API_TOKEN", "token-1")
    monkeypatch.setenv("AWIN_PRODUCT_FEED_API_KEY", "key-1")

    settings = Settings()
    safe = settings.safe_dict()

    assert safe["affiliate_data_dir"] == "/srv/affiliate-data"
    assert safe["feeds_dir"] == "/srv/affiliate-data/feeds"
    assert safe["database_url_configured"] is True
    assert safe["awin_publisher_id_configured"] is True
    assert safe["awin_api_token_configured"] is True
    assert safe["awin_product_feed_api_key_configured"] is True
    assert "password" not in str(safe)
    assert "token-1" not in str(safe)
    assert "key-1" not in str(safe)
