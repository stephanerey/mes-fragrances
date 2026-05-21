from __future__ import annotations

import json

from app.config import get_settings
from app.main import main


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_show_config_masks_secrets(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:super-secret@db:5432/app")
    monkeypatch.setenv("AWIN_API_TOKEN", "super-secret-token")
    monkeypatch.setenv("AWIN_PRODUCT_FEED_API_KEY", "feed-secret")
    monkeypatch.setenv("AWIN_PUBLISHER_ID", "12345")
    clear_settings_cache()

    exit_code = main(["show-config"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "super-secret" not in captured.out
    assert '"database_url_configured": true' in captured.out
    assert '"awin_api_token_configured": true' in captured.out
    assert '"awin_product_feed_api_key_configured": true' in captured.out


def test_import_local_csv_placeholder(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    csv_path = tmp_path / "comas.csv"
    exit_code = main(
        [
            "import-local-csv",
            "--advertiser",
            "105475",
            "--feed-id",
            "97867",
            "--path",
            str(csv_path),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PR01 placeholder only" in captured.out
    assert "No CSV parsing" in captured.out


def test_import_feeds_placeholder(capsys) -> None:
    clear_settings_cache()

    exit_code = main(["import-feeds", "--network", "awin", "--download-only", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Placeholder only" in captured.out
    assert "download_only=True" in captured.out
    assert "No Awin request or database write was performed." in captured.out


def test_awin_list_feeds_missing_credentials(monkeypatch, capsys) -> None:
    monkeypatch.delenv("AWIN_PRODUCT_FEED_API_KEY", raising=False)
    clear_settings_cache()

    exit_code = main(["awin-list-feeds", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "AWIN_PRODUCT_FEED_API_KEY" in captured.err


def test_show_config_still_masks_secret_values(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AWIN_PRODUCT_FEED_API_KEY", "feed-secret")
    clear_settings_cache()

    exit_code = main(["show-config"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["awin_product_feed_api_key_configured"] is True
    assert "feed-secret" not in captured.out
