from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.config import Settings
from app.db import DatabaseService
from app.normalization import (
    NormalizationService,
    clean_identifier,
    detect_exclusion_reasons,
    extract_brand_fallback,
    is_fragrance_category,
    normalize_currency,
    normalize_text,
    parse_concentration,
    parse_price,
    parse_stock,
    parse_volume_ml,
    select_affiliate_url,
    select_image_url,
)
from app.raw_staging import RawStagingService

TEST_DATABASE_URL = os.getenv("AFFILIATE_TEST_DATABASE_URL")

SAMPLE_CSV = (
    "aw_product_id,merchant_product_id,product_name,description,category_name,"
    "merchant_category,search_price,display_price,store_price,currency,merchant_image_url,"
    "large_image,aw_image_url,merchant_thumb_url,aw_deep_link,merchant_deep_link,"
    "brand_name,ean,product_GTIN,upc,mpn,in_stock,stock_quantity,stock_status,"
    "delivery_cost,data_feed_id,merchant_name,merchant_id,category_id,product_type,keywords,specifications\n"
    "1,sku-1,Lancome La Vie Est Belle Eau de Parfum 50 ml,Floral &amp; gourmand,"
    "Fragrance,Fragrance,79.90,\"79,90\",,eur,https://merchant.test/image-1.jpg,"
    "https://merchant.test/large-1.jpg,,,,https://awin.test/1,"
    "https://merchant.test/1,Lancome,111,111,,,1,7,in stock,0,97867,Comas,"
    "105475,12,Perfume,floral fragrance,spray\n"
    "2,sku-2,Dior - Sauvage Coffret EDT 2 x 50 ml,Gift set,Fragrance,Fragrance,,"
    "\"129,99\",,EUR,https://merchant.test/image-2.jpg,,,,,https://merchant.test/2,"
    "Dior,,222,998877665544,,1,3,in stock,5.00,97867,Comas,105475,12,Perfume,"
    "coffret edt,gift box\n"
    "3,sku-3,Chanel Coco Mademoiselle Body Lotion 200 ml,Body lotion,Fragrance,"
    "Fragrance,55.00,55.00,,,https://merchant.test/image-3.jpg,,,,"
    "https://awin.test/3,, ,,,,0,0,out of stock,,97867,Comas,105475,12,"
    "Body Care,body lotion,lotion\n"
    "4,sku-4,Diptyque Candle 190 g,Home candle,Home,Home,45.00,45.00,,EUR,"
    "https://merchant.test/image-4.jpg,,,,https://awin.test/4,,Diptyque,,,,"
    "CANDLE-190,1,8,in stock,7.00,97867,Comas,105475,99,Home,candle,wax candle\n"
)


def build_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "AFFILIATE_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": database_url,
        }
    )


@pytest.fixture()
def staged_database(tmp_path: Path) -> tuple[Settings, str]:
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
    csv_path = tmp_path / "comas.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    RawStagingService(settings).import_local_csv(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
        dry_run=False,
    )
    return settings, TEST_DATABASE_URL


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Déodorant&nbsp;Coffret ", "deodorant coffret"),
        ("L’Interdit Eau de Parfum", "l interdit eau de parfum"),
    ],
)
def test_normalize_text(value: str, expected: str) -> None:
    assert normalize_text(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("129,99 EUR", Decimal("129.99")),
        ("1,299.95", Decimal("1299.95")),
        ("1.299,95", Decimal("1299.95")),
        ("", None),
    ],
)
def test_parse_price(value: str, expected: Decimal | None) -> None:
    assert parse_price(value) == expected


def test_normalize_currency() -> None:
    assert normalize_currency("eur") == "EUR"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("") == "EUR"


@pytest.mark.parametrize(
    ("product_name", "description", "expected"),
    [
        ("Eau de Parfum 50 ml", None, Decimal("50.00")),
        ("Coffret 2 x 50 ml", None, Decimal("100.00")),
        ("Bundle 30+30 ml", None, Decimal("60.00")),
        ("Bottle 1.7 oz / 50 ml", None, Decimal("50.00")),
        ("1900 L'Heure Proust 100 ml", None, Decimal("100.00")),
    ],
)
def test_parse_volume_ml(
    product_name: str,
    description: str | None,
    expected: Decimal,
) -> None:
    assert parse_volume_ml(product_name, description) == expected


@pytest.mark.parametrize(
    ("product_name", "description", "expected"),
    [
        ("Sauvage Eau de Toilette", None, "edt"),
        ("La Vie Est Belle", "Eau de Parfum spray", "edp"),
        ("Fresh scent", "Eau Fraiche body mist", "eau_fraiche"),
        ("Pure perfume", None, None),
    ],
)
def test_parse_concentration(
    product_name: str,
    description: str | None,
    expected: str | None,
) -> None:
    assert parse_concentration(product_name, description) == expected


def test_parse_stock() -> None:
    assert parse_stock("1", "", "").in_stock is True
    assert parse_stock("", "out of stock", "").in_stock is False
    assert parse_stock("", "", "7").in_stock is True


def test_select_image_url_priority() -> None:
    row = {
        "merchant_image_url": "https://merchant.test/image.jpg",
        "large_image": "https://merchant.test/large.jpg",
        "aw_image_url": "https://awin.test/image.jpg",
    }
    assert select_image_url(row) == "https://merchant.test/large.jpg"


def test_select_affiliate_url_priority() -> None:
    row = {
        "aw_deep_link": "https://awin.test/deep-link",
        "merchant_deep_link": "https://merchant.test/deep-link",
    }
    assert select_affiliate_url(row) == "https://awin.test/deep-link"


def test_fragrance_category_filter() -> None:
    assert is_fragrance_category("Fragrance", None) is True
    assert is_fragrance_category("Parfum", None) is True
    assert is_fragrance_category("Home", None) is False


def test_detect_exclusion_reasons() -> None:
    reasons = detect_exclusion_reasons(
        "Coffret Testeur Recharge",
        "Body lotion and shower gel with candle",
    )

    assert reasons == ["set_or_bundle", "tester", "refill", "body_product", "home_fragrance"]


def test_brand_fallback_behavior() -> None:
    assert extract_brand_fallback("Dior - Sauvage Eau de Toilette 50 ml") == "Dior"
    assert extract_brand_fallback("Lancome La Vie Est Belle 50 ml") is None


def test_identifier_extraction() -> None:
    assert clean_identifier(" 123456 ") == "123456"
    assert clean_identifier(" ") is None


def test_normalize_feed_dry_run_does_not_insert_rows(
    staged_database: tuple[Settings, str],
) -> None:
    settings, database_url = staged_database

    report, report_path = NormalizationService(settings).normalize_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert report["status"] == "success"
    assert report["raw_rows_total"] == 4
    assert report["normalized_rows_inserted"] == 0
    assert report["rows_fragrance"] == 3
    assert report["rows_excluded"] == 2
    assert report["rows_excluded_set_or_bundle"] == 1
    assert report["rows_excluded_body_product"] == 1
    assert report["rows_excluded_home_fragrance"] == 0
    assert report["rows_with_brand"] == 3
    assert report["rows_with_any_identifier"] == 2
    assert report["rows_with_volume_ml"] == 3
    assert report["rows_with_concentration"] == 2
    assert report["rows_with_price"] == 4
    assert report["rows_with_affiliate_url"] == 4
    assert report["rows_with_image_url"] == 4
    assert report["rows_actionable_fragrance"] == 1
    assert report_path.exists()

    with psycopg.connect(database_url) as conn:
        normalized_items = conn.execute("select count(*) from normalized_feed_items").fetchone()[0]

    assert normalized_items == 0


def test_normalize_feed_non_dry_run_inserts_rows_and_is_idempotent(
    staged_database: tuple[Settings, str],
) -> None:
    settings, database_url = staged_database
    service = NormalizationService(settings)

    first_report, _ = service.normalize_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )
    second_report, _ = service.normalize_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    assert first_report["normalized_rows_inserted"] == 4
    assert first_report["normalized_rows_updated"] == 0
    assert first_report["normalized_rows_duplicates"] == 0
    assert second_report["normalized_rows_inserted"] == 0
    assert second_report["normalized_rows_updated"] == 0
    assert second_report["normalized_rows_duplicates"] == 4

    with psycopg.connect(database_url) as conn:
        normalized_items = conn.execute(
            "select count(*) from normalized_feed_items"
        ).fetchone()[0]
        excluded_rows = conn.execute(
            """
            select count(*)
            from normalized_feed_items
            where is_excluded = true
            """
        ).fetchone()[0]
        first_item = conn.execute(
            """
            select title, normalized_title, brand, normalized_brand, concentration, volume_ml
            from normalized_feed_items
            order by raw_feed_item_id
            limit 1
            """
        ).fetchone()
        offers = conn.execute("select count(*) from offers").fetchone()[0]
        candidates = conn.execute("select count(*) from product_match_candidates").fetchone()[0]
        mappings = conn.execute("select count(*) from external_product_mappings").fetchone()[0]

    assert normalized_items == 4
    assert excluded_rows == 2
    assert first_item == (
        "Lancome La Vie Est Belle Eau de Parfum 50 ml",
        "lancome la vie est belle eau de parfum 50 ml",
        "Lancome",
        "lancome",
        "edp",
        Decimal("50.00"),
    )
    assert offers == 0
    assert candidates == 0
    assert mappings == 0


def test_normalize_feed_with_import_run_limit(
    staged_database: tuple[Settings, str],
) -> None:
    settings, _ = staged_database

    report, _ = NormalizationService(settings).normalize_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
        import_run_id=1,
        limit=2,
    )

    assert report["import_run_id"] == 1
    assert report["raw_rows_total"] == 2
    assert report["raw_rows_available"] == 4
