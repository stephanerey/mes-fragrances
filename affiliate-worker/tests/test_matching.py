from __future__ import annotations

import csv
import os
from decimal import Decimal
from io import StringIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.config import Settings
from app.db import DatabaseService
from app.matching import (
    MatchingService,
    brand_compatible,
    build_perfume_match_key,
    fuzzy_name_score,
)
from app.normalization import NormalizationService
from app.raw_staging import RawStagingService

TEST_DATABASE_URL = os.getenv("AFFILIATE_TEST_DATABASE_URL")

SAMPLE_HEADERS = [
    "aw_product_id",
    "merchant_product_id",
    "product_name",
    "description",
    "category_name",
    "merchant_category",
    "search_price",
    "display_price",
    "store_price",
    "currency",
    "merchant_image_url",
    "large_image",
    "aw_image_url",
    "merchant_thumb_url",
    "aw_deep_link",
    "merchant_deep_link",
    "brand_name",
    "ean",
    "product_GTIN",
    "upc",
    "mpn",
    "in_stock",
    "stock_quantity",
    "stock_status",
    "delivery_cost",
    "data_feed_id",
    "merchant_name",
    "merchant_id",
    "category_id",
    "product_type",
    "keywords",
    "specifications",
]


def build_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "AFFILIATE_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": database_url,
        }
    )


def build_csv(rows: list[dict[str, str]]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SAMPLE_HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def base_feed_rows() -> list[dict[str, str]]:
    return [
        {
            "aw_product_id": "1",
            "merchant_product_id": "sku-1",
            "product_name": "Lancome La Vie Est Belle Eau de Parfum 50 ml",
            "description": "Floral & gourmand",
            "category_name": "Fragrance",
            "merchant_category": "Fragrance",
            "search_price": "79.90",
            "display_price": "79,90",
            "store_price": "",
            "currency": "EUR",
            "merchant_image_url": "https://merchant.test/image-1.jpg",
            "large_image": "https://merchant.test/large-1.jpg",
            "aw_image_url": "",
            "merchant_thumb_url": "",
            "aw_deep_link": "https://awin.test/1",
            "merchant_deep_link": "https://merchant.test/1",
            "brand_name": "Lancome",
            "ean": "111",
            "product_GTIN": "111",
            "upc": "",
            "mpn": "LVB-50",
            "in_stock": "1",
            "stock_quantity": "7",
            "stock_status": "in stock",
            "delivery_cost": "0",
            "data_feed_id": "97867",
            "merchant_name": "Comas",
            "merchant_id": "105475",
            "category_id": "12",
            "product_type": "Perfume",
            "keywords": "floral fragrance",
            "specifications": "spray",
        },
        {
            "aw_product_id": "2",
            "merchant_product_id": "sku-2",
            "product_name": "Dior Sauvage Coffret EDT 2 x 50 ml",
            "description": "Gift set",
            "category_name": "Fragrance",
            "merchant_category": "Fragrance",
            "search_price": "",
            "display_price": "129,99",
            "store_price": "",
            "currency": "EUR",
            "merchant_image_url": "https://merchant.test/image-2.jpg",
            "large_image": "",
            "aw_image_url": "",
            "merchant_thumb_url": "",
            "aw_deep_link": "https://awin.test/2",
            "merchant_deep_link": "https://merchant.test/2",
            "brand_name": "Dior",
            "ean": "",
            "product_GTIN": "",
            "upc": "998877665544",
            "mpn": "",
            "in_stock": "1",
            "stock_quantity": "3",
            "stock_status": "in stock",
            "delivery_cost": "5.00",
            "data_feed_id": "97867",
            "merchant_name": "Comas",
            "merchant_id": "105475",
            "category_id": "12",
            "product_type": "Perfume",
            "keywords": "coffret edt",
            "specifications": "gift box",
        },
    ]


def prepare_database(
    tmp_path: Path,
    *,
    rows: list[dict[str, str]] | None = None,
    include_identifier_columns: bool = False,
    perfume_rows: list[tuple[str, str, str, str | None]] | None = None,
) -> tuple[Settings, str, list[str]]:
    if not TEST_DATABASE_URL:
        pytest.skip("AFFILIATE_TEST_DATABASE_URL is not configured")

    identifier_columns = ""
    if include_identifier_columns:
        identifier_columns = ", ean text, gtin text, upc text, mpn text"

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
        conn.execute(
            f"""
            create table perfumes (
                id uuid primary key,
                slug varchar not null,
                name varchar not null,
                brand varchar not null{identifier_columns},
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

        if perfume_rows is None:
            perfume_rows = [
                (str(uuid4()), "la-vie-est-belle", "La Vie Est Belle", "Lancome"),
                (str(uuid4()), "idole", "Idole", "Lancome"),
                (str(uuid4()), "alien", "Alien", "Mugler"),
            ]

        for perfume_id, slug, name, brand in perfume_rows:
            if include_identifier_columns and name == "La Vie Est Belle":
                conn.execute(
                    """
                    insert into perfumes (id, slug, name, brand, ean, gtin, mpn)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (perfume_id, slug, name, brand, "111", "111", "LVB-50"),
                )
            else:
                conn.execute(
                    """
                    insert into perfumes (id, slug, name, brand)
                    values (%s, %s, %s, %s)
                    """,
                    (perfume_id, slug, name, brand),
                )

    settings = build_settings(tmp_path, TEST_DATABASE_URL)
    DatabaseService(settings).migrate_db()
    csv_path = tmp_path / "matching.csv"
    csv_path.write_text(build_csv(rows or base_feed_rows()), encoding="utf-8")
    RawStagingService(settings).import_local_csv(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
        dry_run=False,
    )
    NormalizationService(settings).normalize_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )
    return settings, TEST_DATABASE_URL, [row[0] for row in perfume_rows]


def test_build_perfume_match_key() -> None:
    assert (
        build_perfume_match_key(
            "Lancome La Vie Est Belle Eau de Parfum 50 ml",
            brand="Lancome",
            concentration="edp",
            volume_ml=Decimal("50.00"),
        )
        == "la vie est belle"
    )


@pytest.mark.parametrize(
    ("title", "brand", "concentration", "volume_ml", "expected"),
    [
        ("Aigner Debut Eau de Parfum 100 ml", "Aigner", "edp", Decimal("100.00"), "debut"),
        ("Memo Paris Kedu Eau de Parfum 10 ml", "Memo Paris", "edp", Decimal("10.00"), "kedu"),
        (
            "ELEVEN LEGENDS Limited Edition Extrait 80 ml",
            "ELEVEN LEGENDS",
            None,
            Decimal("80.00"),
            "limited edition extrait",
        ),
        (
            "Van Cleef & Arpels Orchidee Vanille Eau de Parfum 75 ml",
            "Van Cleef & Arpels",
            "edp",
            Decimal("75.00"),
            "orchidee vanille",
        ),
    ],
)
def test_build_perfume_match_key_handles_integer_volumes_without_truncating(
    title: str,
    brand: str,
    concentration: str | None,
    volume_ml: Decimal,
    expected: str,
) -> None:
    assert (
        build_perfume_match_key(
            title,
            brand=brand,
            concentration=concentration,
            volume_ml=volume_ml,
        )
        == expected
    )


def test_brand_compatible() -> None:
    assert brand_compatible("Lancôme", "Lancome") is True
    assert brand_compatible("Lancome", "Dior") is False


def test_fuzzy_name_score_prefers_close_matches() -> None:
    assert fuzzy_name_score("la vie est belle", "la vie est belle") == 100.0
    assert fuzzy_name_score("la vie est belle", "alien") < 50


def test_match_offers_dry_run_reports_identifier_matching_disabled(
    tmp_path: Path,
) -> None:
    settings, _, _ = prepare_database(tmp_path)

    report, report_path = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert report["status"] == "success"
    assert report["catalog_identifier_fields_available"] is False
    assert report["exact_identifier_matching_enabled"] is False
    assert report["rows_actionable_input"] == 1
    assert report["rows_skipped_excluded"] == 1
    assert report["rows_matched_total"] == 1
    assert report["rows_matched_deterministic_key"] == 1
    assert report["offers_inserted"] == 0
    assert report_path.exists()


def test_locked_external_mapping_has_priority_over_heuristics(tmp_path: Path) -> None:
    settings, database_url, perfume_ids = prepare_database(tmp_path)
    target_perfume_id = perfume_ids[1]

    with psycopg.connect(database_url, autocommit=True) as conn:
        advertiser_id = conn.execute(
            """
            select id
            from advertisers
            where network = 'awin'
              and network_advertiser_id = '105475'
            """
        ).fetchone()[0]
        conn.execute(
            """
            insert into external_product_mappings (
                advertiser_id,
                network_product_id,
                merchant_product_id,
                perfume_id,
                confidence,
                locked
            )
            values (%s, %s, %s, %s, %s, true)
            """,
            (advertiser_id, "1", "sku-1", target_perfume_id, Decimal("100.00")),
        )

    report, _ = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert report["rows_matched_locked_mapping"] == 1
    assert report["sample_matches"][0]["perfume_id"] == target_perfume_id


def test_exact_identifier_matching_enabled_when_catalog_has_identifier_fields(
    tmp_path: Path,
) -> None:
    settings, _, _ = prepare_database(tmp_path, include_identifier_columns=True)

    report, _ = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert report["catalog_identifier_fields_available"] is True
    assert report["exact_identifier_matching_enabled"] is True
    assert report["rows_matched_exact_identifier"] == 1


def test_ambiguity_prevents_auto_match(tmp_path: Path) -> None:
    perfume_rows = [
        (str(uuid4()), "alien", "Alien", "Mugler"),
        (str(uuid4()), "alien-limited", "Alien", "Mugler"),
    ]
    rows = [
        {
            **base_feed_rows()[0],
            "aw_product_id": "9",
            "merchant_product_id": "sku-9",
            "product_name": "Mugler Alien Eau de Parfum 60 ml",
            "brand_name": "Mugler",
            "ean": "",
            "product_GTIN": "",
            "mpn": "",
        }
    ]
    settings, _, _ = prepare_database(
        tmp_path,
        rows=rows,
        perfume_rows=perfume_rows,
    )

    report, _ = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert report["rows_matched_total"] == 0
    assert report["rows_needs_review"] == 1


def test_excluded_row_prevents_offer_creation(tmp_path: Path) -> None:
    settings, database_url, _ = prepare_database(tmp_path)

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            update normalized_feed_items
            set is_excluded = true,
                exclusion_reasons = '["set_or_bundle"]'::jsonb
            where network_product_id = '1'
            """
        )

    report, _ = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        offers_count = conn.execute("select count(*) from offers").fetchone()[0]

    assert report["rows_skipped_excluded"] == 2
    assert offers_count == 0


def test_missing_price_prevents_offer_creation(tmp_path: Path) -> None:
    settings, database_url, _ = prepare_database(tmp_path)

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            update normalized_feed_items
            set price = null
            where network_product_id = '1'
            """
        )

    report, _ = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        offers_count = conn.execute("select count(*) from offers").fetchone()[0]

    assert report["rows_skipped_missing_required"] == 1
    assert offers_count == 0


def test_missing_affiliate_url_prevents_offer_creation(tmp_path: Path) -> None:
    settings, database_url, _ = prepare_database(tmp_path)

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            update normalized_feed_items
            set affiliate_url = null
            where network_product_id = '1'
            """
        )

    report, _ = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        offers_count = conn.execute("select count(*) from offers").fetchone()[0]

    assert report["rows_skipped_missing_required"] == 1
    assert offers_count == 0


def test_dry_run_does_not_insert_offers(tmp_path: Path) -> None:
    settings, database_url, _ = prepare_database(tmp_path)

    report, _ = MatchingService(settings).match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    with psycopg.connect(database_url) as conn:
        offers_count = conn.execute("select count(*) from offers").fetchone()[0]

    assert report["offers_inserted"] == 0
    assert offers_count == 0


def test_offer_insert_update_and_idempotent_second_run(tmp_path: Path) -> None:
    settings, database_url, perfume_ids = prepare_database(tmp_path)
    service = MatchingService(settings)

    first_report, _ = service.match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )
    second_report, _ = service.match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        offer_row = conn.execute(
            """
            select perfume_id, match_status, match_method, missed_imports, active, metadata
            from offers
            order by id
            limit 1
            """
        ).fetchone()
        offers_count = conn.execute("select count(*) from offers").fetchone()[0]
        perfume_offers_count = conn.execute("select count(*) from perfume_offers").fetchone()[0]
        candidates_count = conn.execute(
            "select count(*) from product_match_candidates"
        ).fetchone()[0]
        mappings_count = conn.execute(
            "select count(*) from external_product_mappings"
        ).fetchone()[0]

    assert first_report["offers_inserted"] == 1
    assert second_report["offers_inserted"] == 0
    assert second_report["offers_unchanged"] == 1
    assert offers_count == 1
    assert str(offer_row[0]) == perfume_ids[0]
    assert offer_row[1] == "matched_deterministic_key"
    assert offer_row[2] == "deterministic_key"
    assert offer_row[3] == 0
    assert offer_row[4] is True
    assert offer_row[5]["network_feed_id"] == "97867"
    assert perfume_offers_count == 0
    assert candidates_count == 0
    assert mappings_count == 0


def test_price_change_sets_last_price_change_at_and_preserves_when_unchanged(
    tmp_path: Path,
) -> None:
    settings, database_url, _ = prepare_database(tmp_path)
    service = MatchingService(settings)

    service.match_offers(advertiser_id="105475", feed_id="97867", dry_run=False)
    with psycopg.connect(database_url) as conn:
        before_change = conn.execute(
            "select last_price_change_at from offers order by id limit 1"
        ).fetchone()[0]
        conn.execute(
            """
            update normalized_feed_items
            set price = 89.90
            where network_product_id = '1'
            """
        )

    second_report, _ = service.match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )
    with psycopg.connect(database_url) as conn:
        after_change = conn.execute(
            "select price, last_price_change_at from offers order by id limit 1"
        ).fetchone()
        stable_timestamp = after_change[1]

    third_report, _ = service.match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )
    with psycopg.connect(database_url) as conn:
        after_unchanged = conn.execute(
            "select last_price_change_at from offers order by id limit 1"
        ).fetchone()[0]

    assert second_report["offers_price_changed"] == 1
    assert after_change[0] == Decimal("89.90")
    assert after_change[1] >= before_change
    assert third_report["offers_price_changed"] == 0
    assert after_unchanged == stable_timestamp


def test_stale_offer_increment_and_deactivation(tmp_path: Path) -> None:
    settings, database_url, perfume_ids = prepare_database(tmp_path)
    service = MatchingService(settings)

    with psycopg.connect(database_url, autocommit=True) as conn:
        advertiser_id = conn.execute(
            """
            select id
            from advertisers
            where network = 'awin'
              and network_advertiser_id = '105475'
            """
        ).fetchone()[0]
        conn.execute(
            """
            insert into offers (
                advertiser_id,
                perfume_id,
                network,
                network_product_id,
                merchant_product_id,
                title,
                description,
                price,
                currency,
                affiliate_url,
                active,
                missed_imports,
                metadata
            )
            values (%s, %s, 'awin', 'ghost', 'ghost', 'Ghost', null, 10.00, 'EUR',
                    'https://ghost.test', true, 2, %s)
            """,
            (
                advertiser_id,
                perfume_ids[2],
                Jsonb({"network_feed_id": "97867"}),
            ),
        )

    report, _ = service.match_offers(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        stale_row = conn.execute(
            """
            select missed_imports, active
            from offers
            where network_product_id = 'ghost'
            """
        ).fetchone()

    assert report["stale_offers_incremented"] == 1
    assert report["stale_offers_deactivated"] == 1
    assert stale_row == (3, False)


def test_seen_offer_resets_missed_imports(tmp_path: Path) -> None:
    settings, database_url, _ = prepare_database(tmp_path)
    service = MatchingService(settings)
    service.match_offers(advertiser_id="105475", feed_id="97867", dry_run=False)

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            update offers
            set missed_imports = 2,
                active = false
            where network_product_id = '1'
            """
        )

    service.match_offers(advertiser_id="105475", feed_id="97867", dry_run=False)

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select missed_imports, active
            from offers
            where network_product_id = '1'
            """
        ).fetchone()

    assert row == (0, True)
