from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.config import Settings
from app.db import DatabaseService
from app.raw_staging import (
    RawStagingError,
    RawStagingService,
    calculate_raw_hash,
    calculate_sha256,
    canonical_row_json,
)

TEST_DATABASE_URL = os.getenv("AFFILIATE_TEST_DATABASE_URL")

SAMPLE_CSV = (
    "aw_product_id,merchant_product_id,product_name,description,category_name,"
    "merchant_category,search_price,display_price,currency,merchant_image_url,"
    "aw_deep_link,merchant_deep_link,brand_name,ean,product_GTIN,mpn,in_stock,"
    "delivery_cost,data_feed_id,merchant_name,merchant_id,category_id\n"
    "1,sku-1,Acme Eau de Parfum 100ml,Desc,Fragrance,Fragrance,79.90,79.90,EUR,"
    "https://img.test/1.jpg,https://awin.test/1,https://merchant.test/1,Acme,"
    "111,111,MPN-1,1,4.95,97867,Comas,105475,12\n"
    "2,sku-2,Acme Eau de Toilette 50ml,Desc,Fragrance,Fragrance,49.90,49.90,EUR,"
    "https://img.test/2.jpg,https://awin.test/2,https://merchant.test/2,Acme,"
    "222,222,MPN-2,1,4.95,97867,Comas,105475,12\n"
    ",,Mystery Eau de Cologne 75ml,Desc,Fragrance,Fragrance,39.90,39.90,EUR,"
    "https://img.test/3.jpg,https://awin.test/3,https://merchant.test/3,Acme,"
    "333,333,,1,4.95,97867,Comas,105475,12\n"
)


def build_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "AFFILIATE_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": database_url,
        }
    )


@pytest.fixture()
def migrated_postgres_database(tmp_path: Path) -> tuple[Settings, str]:
    if not TEST_DATABASE_URL:
        pytest.skip("AFFILIATE_TEST_DATABASE_URL is not configured")

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
        conn.execute(
            """
            create table perfumes (
                id uuid primary key,
                slug varchar not null,
                name varchar not null,
                brand varchar not null,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
        conn.execute(
            """
            create table perfume_offers (
                id uuid primary key,
                perfume_id uuid not null references perfumes(id),
                merchant_name varchar not null,
                price numeric not null,
                currency varchar not null,
                affiliate_url text not null,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
        conn.execute(
            """
            insert into perfumes (id, slug, name, brand)
            values (%s, %s, %s, %s)
            """,
            (uuid4(), "test-perfume", "Test Perfume", "Test Brand"),
        )

    settings = build_settings(tmp_path, TEST_DATABASE_URL)
    DatabaseService(settings).migrate_db()
    return settings, TEST_DATABASE_URL


def write_sample_csv(path: Path, *, gzip_encoded: bool = False) -> bytes:
    payload = SAMPLE_CSV.encode("utf-8")
    if gzip_encoded:
        payload = gzip.compress(payload)
    path.write_bytes(payload)
    return payload


def test_raw_hash_is_deterministic() -> None:
    first = {"b": "2", "a": "1"}
    second = {"a": "1", "b": "2"}

    assert canonical_row_json(first) == '{"a":"1","b":"2"}'
    assert calculate_raw_hash(first) == calculate_raw_hash(second)


def test_import_local_csv_dry_run_does_not_insert_db_rows(
    migrated_postgres_database: tuple[Settings, str],
    tmp_path: Path,
) -> None:
    settings, database_url = migrated_postgres_database
    csv_path = tmp_path / "comas.csv"
    payload = write_sample_csv(csv_path)

    report, report_path = RawStagingService(settings).import_local_csv(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
        dry_run=True,
    )

    assert report["status"] == "success"
    assert report["dry_run"] is True
    assert report["rows_total"] == 3
    assert report["rows_inserted"] == 0
    assert report["rows_duplicates"] is None
    assert report["import_run_id"] is None
    assert report["source"] == "local_file"
    assert report["source_file_sha256"] == hashlib.sha256(payload).hexdigest()
    assert report_path.exists()

    with psycopg.connect(database_url) as conn:
        import_runs = conn.execute("select count(*) from feed_import_runs").fetchone()[0]
        raw_items = conn.execute("select count(*) from raw_feed_items").fetchone()[0]

    assert import_runs == 0
    assert raw_items == 0


def test_import_local_csv_non_dry_run_creates_run_and_raw_payloads(
    migrated_postgres_database: tuple[Settings, str],
    tmp_path: Path,
) -> None:
    settings, database_url = migrated_postgres_database
    csv_path = tmp_path / "comas.csv"
    write_sample_csv(csv_path)

    report, _ = RawStagingService(settings).import_local_csv(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
        dry_run=False,
    )

    assert report["status"] == "success"
    assert report["rows_total"] == 3
    assert report["rows_inserted"] == 3
    assert report["rows_duplicates"] == 0
    assert report["rows_missing_stable_external_ids"] == 1
    assert isinstance(report["import_run_id"], int)

    with psycopg.connect(database_url) as conn:
        import_run = conn.execute(
            """
            select status, rows_total, rows_errors, source_file_sha256
            from feed_import_runs
            order by id desc
            limit 1
            """
        ).fetchone()
        raw_item = conn.execute(
            """
            select network, network_product_id, merchant_product_id, raw_payload, raw_hash
            from raw_feed_items
            order by id
            limit 1
            """
        ).fetchone()
        raw_items = conn.execute("select count(*) from raw_feed_items").fetchone()[0]
        offers = conn.execute("select count(*) from offers").fetchone()[0]
        candidates = conn.execute("select count(*) from product_match_candidates").fetchone()[0]
        mappings = conn.execute("select count(*) from external_product_mappings").fetchone()[0]

    assert import_run[0] == "success"
    assert import_run[1] == 3
    assert import_run[2] == 0
    assert raw_items == 3
    assert raw_item[0] == "awin"
    assert raw_item[1] == "1"
    assert raw_item[2] == "sku-1"
    assert raw_item[3]["product_name"] == "Acme Eau de Parfum 100ml"
    assert raw_item[4] == calculate_raw_hash(raw_item[3])
    assert offers == 0
    assert candidates == 0
    assert mappings == 0


def test_repeated_import_is_idempotent_and_counts_duplicates(
    migrated_postgres_database: tuple[Settings, str],
    tmp_path: Path,
) -> None:
    settings, database_url = migrated_postgres_database
    csv_path = tmp_path / "comas.csv"
    write_sample_csv(csv_path)
    service = RawStagingService(settings)

    first_report, _ = service.import_local_csv(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
        dry_run=False,
    )
    second_report, _ = service.import_local_csv(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
        dry_run=False,
    )

    assert first_report["rows_inserted"] == 3
    assert first_report["rows_duplicates"] == 0
    assert second_report["rows_inserted"] == 0
    assert second_report["rows_duplicates"] == 3

    with psycopg.connect(database_url) as conn:
        import_runs = conn.execute("select count(*) from feed_import_runs").fetchone()[0]
        raw_items = conn.execute("select count(*) from raw_feed_items").fetchone()[0]

    assert import_runs == 2
    assert raw_items == 3


def test_gzip_csv_input_detected_by_magic_bytes(
    migrated_postgres_database: tuple[Settings, str],
    tmp_path: Path,
) -> None:
    settings, _ = migrated_postgres_database
    gzip_path = tmp_path / "comas.data"
    write_sample_csv(gzip_path, gzip_encoded=True)

    report, _ = RawStagingService(settings).import_local_csv(
        advertiser_id="105475",
        feed_id="97867",
        path=gzip_path,
        dry_run=True,
    )

    assert report["compression"] == "gzip"
    assert report["rows_total"] == 3


def test_missing_file_returns_clean_error(
    migrated_postgres_database: tuple[Settings, str],
    tmp_path: Path,
) -> None:
    settings, _ = migrated_postgres_database

    with pytest.raises(RawStagingError, match="Feed file not found"):
        RawStagingService(settings).import_local_csv(
            advertiser_id="105475",
            feed_id="97867",
            path=tmp_path / "missing.csv",
            dry_run=True,
        )


def test_missing_feed_seed_returns_clean_error(
    migrated_postgres_database: tuple[Settings, str],
    tmp_path: Path,
) -> None:
    settings, database_url = migrated_postgres_database
    csv_path = tmp_path / "comas.csv"
    write_sample_csv(csv_path)

    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            delete from affiliate_feeds
            where network = 'awin'
              and network_feed_id = '97867'
            """
        )

    with pytest.raises(RawStagingError, match="Run migrate-db from PR04/PR05 first"):
        RawStagingService(settings).import_local_csv(
            advertiser_id="105475",
            feed_id="97867",
            path=csv_path,
            dry_run=True,
        )


def test_remote_configured_url_import_uses_env_and_redacts_secret(
    migrated_postgres_database: tuple[Settings, str],
) -> None:
    settings, _ = migrated_postgres_database
    payload = SAMPLE_CSV.encode("utf-8")
    requested_urls: list[str] = []

    def fake_fetcher(url: str) -> bytes:
        requested_urls.append(url)
        return payload

    secret_url = (
        "https://productdata.awin.com/datafeed/download/apikey/"
        "super-secret/fid/97867/format/csv/delimiter/%2C/compression/gzip"
    )
    service = RawStagingService(
        settings,
        fetcher=fake_fetcher,
        environ={"AWIN_FEED_URL_105475_97867": secret_url},
    )

    report, report_path = service.import_remote_feed(
        network="awin",
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert requested_urls == [secret_url]
    assert report["source"] == "configured_env"
    assert report["configured_feed_url_env_var"] == "AWIN_FEED_URL_105475_97867"
    assert report["download_url_source"] == "configured_env"
    assert report["source_file_or_url_redacted"] is True
    assert report["source_reference"] != secret_url
    assert "<redacted>" in str(report["source_reference"])
    assert "super-secret" not in report_path.read_text(encoding="utf-8")


def test_calculate_sha256_matches_payload() -> None:
    payload = b"abc123"
    assert calculate_sha256(payload) == hashlib.sha256(payload).hexdigest()
