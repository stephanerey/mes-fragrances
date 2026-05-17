from __future__ import annotations

from pathlib import Path

from app.config import load_settings


def test_load_settings_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AFFILIATE_DATA_DIR", raising=False)

    settings = load_settings()

    assert settings.database_url is None
    assert settings.import_mode == "development"
    assert settings.log_level == "INFO"
    assert settings.data_dir == Path("/data")
    assert settings.deactivate_after_missed_imports == 3
    assert settings.match_auto_threshold == 95.0
    assert settings.match_review_threshold == 85.0


def test_load_settings_custom_values(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("AFFILIATE_IMPORT_MODE", "production")
    monkeypatch.setenv("AFFILIATE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS", "5")
    monkeypatch.setenv("AFFILIATE_MATCH_AUTO_THRESHOLD", "97")
    monkeypatch.setenv("AFFILIATE_MATCH_REVIEW_THRESHOLD", "88")

    settings = load_settings()

    assert settings.database_url == "postgresql://example"
    assert settings.import_mode == "production"
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == tmp_path
    assert settings.deactivate_after_missed_imports == 5
    assert settings.match_auto_threshold == 97.0
    assert settings.match_review_threshold == 88.0
