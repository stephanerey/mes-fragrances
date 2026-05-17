from __future__ import annotations

from pathlib import Path

from app.main import main


def test_cli_help_returns_zero(capsys):
    exit_code = main(["--help"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Affiliate feed worker" in captured.out


def test_show_config_does_not_print_secrets(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AWIN_API_TOKEN", "super-secret-token")
    monkeypatch.setenv("AWIN_PRODUCT_FEED_API_KEY", "super-secret-feed-key")

    exit_code = main(["show-config"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "super-secret-token" not in captured.out
    assert "super-secret-feed-key" not in captured.out
    assert '"awin_api_token_configured": true' in captured.out
    assert '"awin_product_feed_api_key_configured": true' in captured.out


def test_inspect_db_without_database_url_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    exit_code = main(["inspect-db"])

    assert exit_code == 1


def test_migrate_db_without_database_url_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    exit_code = main(["migrate-db"])

    assert exit_code == 1


def test_import_local_csv_missing_file_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path))

    exit_code = main([
        "import-local-csv",
        "--advertiser",
        "105475",
        "--feed-id",
        "97867",
        "--path",
        str(tmp_path / "missing.csv"),
    ])

    assert exit_code == 2


def test_import_local_csv_existing_file_writes_skeleton_report(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path))
    csv_path = tmp_path / "comas.csv"
    csv_path.write_text("product_name,category_name\nExample,Fragrance\n", encoding="utf-8")

    exit_code = main([
        "import-local-csv",
        "--advertiser",
        "105475",
        "--feed-id",
        "97867",
        "--path",
        str(csv_path),
        "--dry-run",
    ])

    assert exit_code == 0
    report_path = Path(tmp_path) / "reports" / "last_import_local_csv_skeleton.json"
    assert report_path.exists()
    captured = capsys.readouterr()
    assert '"status": "validated"' in captured.out
