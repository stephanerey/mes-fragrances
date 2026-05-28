from __future__ import annotations

import json
from pathlib import Path

from app.config import get_settings
from app.main import main


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def isolate_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path / "data"))
    clear_settings_cache()


def test_show_config_masks_secrets(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
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


def test_import_local_csv_requires_database_url(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
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
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_import_feeds_placeholder(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)

    exit_code = main(["import-feeds", "--network", "awin", "--download-only", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Placeholder only" in captured.out
    assert "download_only=True" in captured.out
    assert "No Awin request or database write was performed." in captured.out


def test_import_feeds_raw_stage_only_requires_database_url(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "AWIN_FEED_URL_105475_97867",
        "https://productdata.awin.com/datafeed/download/apikey/super-secret/fid/97867",
    )
    clear_settings_cache()

    exit_code = main(
        [
            "import-feeds",
            "--network",
            "awin",
            "--raw-stage-only",
            "--advertiser",
            "105475",
            "--feed-id",
            "97867",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err
    assert "super-secret" not in captured.err


def test_awin_list_feeds_missing_credentials(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("AWIN_PRODUCT_FEED_API_KEY", raising=False)
    clear_settings_cache()

    exit_code = main(["awin-list-feeds", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "AWIN_PRODUCT_FEED_API_KEY" in captured.err


def test_awin_download_feed_missing_credentials_without_configured_url(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("AWIN_PRODUCT_FEED_API_KEY", raising=False)
    monkeypatch.delenv("AWIN_FEED_URL_105475_97867", raising=False)
    clear_settings_cache()

    exit_code = main(
        ["awin-download-feed", "--advertiser", "105475", "--feed-id", "97867", "--dry-run"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "AWIN_PRODUCT_FEED_API_KEY" in captured.err


def test_show_config_still_masks_secret_values(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("AWIN_PRODUCT_FEED_API_KEY", "feed-secret")
    clear_settings_cache()

    exit_code = main(["show-config"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["awin_product_feed_api_key_configured"] is True
    assert "feed-secret" not in captured.out


def test_preprocess_feed_missing_credentials_without_path(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("AWIN_PRODUCT_FEED_API_KEY", raising=False)
    monkeypatch.delenv("AWIN_FEED_URL_105475_97867", raising=False)
    clear_settings_cache()

    exit_code = main(["preprocess-feed", "--advertiser", "105475", "--feed-id", "97867"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "AWIN_PRODUCT_FEED_API_KEY" in captured.err


def test_preprocess_feed_local_path_without_credentials(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("AWIN_PRODUCT_FEED_API_KEY", raising=False)
    monkeypatch.delenv("AWIN_FEED_URL_105475_97867", raising=False)
    clear_settings_cache()

    csv_path = tmp_path / "local.csv"
    csv_path.write_text(
        (
            "aw_product_id,merchant_product_id,product_name,aw_deep_link,"
            "merchant_image_url,description,merchant_category,search_price,"
            "merchant_name,merchant_id,category_name,category_id,currency,"
            "display_price,data_feed_id\n"
            "1,sku-1,Test Product,https://example.test/deep-link,"
            "https://example.test/image.jpg,Description,Fragrance,10.00,"
            "Comas,105475,Fragrance,12,EUR,10,97867\n"
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "preprocess-feed",
            "--advertiser",
            "105475",
            "--feed-id",
            "97867",
            "--path",
            str(csv_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "rows_total=1" in captured.out
    assert "source=local_file" in captured.out


def test_normalize_feed_requires_database_url(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(["normalize-feed", "--advertiser", "105475", "--feed-id", "97867"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_match_offers_requires_database_url(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(["match-offers", "--advertiser", "105475", "--feed-id", "97867"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_create_candidates_requires_database_url(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(["create-candidates", "--advertiser", "105475", "--feed-id", "97867"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_sync_perfume_insert_candidates_requires_database_url(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(
        [
            "sync-perfume-insert-candidates",
            "--advertiser",
            "105475",
            "--feed-id",
            "97867",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_refresh_product_match_candidates_requires_database_url(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(
        [
            "refresh-product-match-candidates",
            "--advertiser",
            "105475",
            "--feed-id",
            "97867",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_run_affiliate_pipeline_requires_database_url(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(["run-affiliate-pipeline", "--network", "awin", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_inspect_db_requires_database_url(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(["inspect-db"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err


def test_migrate_db_requires_database_url(monkeypatch, capsys, tmp_path: Path) -> None:
    isolate_settings(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clear_settings_cache()

    exit_code = main(["migrate-db", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DATABASE_URL" in captured.err
