from __future__ import annotations

import csv
import os
from io import StringIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.candidates import CandidateService
from app.config import Settings
from app.db import DatabaseService
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


def base_rows() -> list[dict[str, str]]:
    return [
        {
            "aw_product_id": "1",
            "merchant_product_id": "sku-1",
            "product_name": "Lancome La Vie Est Belle Eau de Parfum 50 ml",
            "description": "Floral",
            "category_name": "Fragrance",
            "merchant_category": "Fragrance",
            "search_price": "79.90",
            "display_price": "79.90",
            "store_price": "",
            "currency": "EUR",
            "merchant_image_url": "https://merchant.test/image-1.jpg",
            "large_image": "",
            "aw_image_url": "",
            "merchant_thumb_url": "",
            "aw_deep_link": "https://awin.test/1",
            "merchant_deep_link": "https://merchant.test/1",
            "brand_name": "Lancome",
            "ean": "",
            "product_GTIN": "",
            "upc": "",
            "mpn": "",
            "in_stock": "1",
            "stock_quantity": "3",
            "stock_status": "in stock",
            "delivery_cost": "0",
            "data_feed_id": "97867",
            "merchant_name": "Example Merchant",
            "merchant_id": "105475",
            "category_id": "12",
            "product_type": "Perfume",
            "keywords": "fragrance",
            "specifications": "spray",
        },
        {
            "aw_product_id": "2",
            "merchant_product_id": "sku-2",
            "product_name": "Armani My Waye 50 ml",
            "description": "Floral nectar",
            "category_name": "Fragrance",
            "merchant_category": "Fragrance",
            "search_price": "89.90",
            "display_price": "89.90",
            "store_price": "",
            "currency": "EUR",
            "merchant_image_url": "https://merchant.test/image-2.jpg",
            "large_image": "",
            "aw_image_url": "",
            "merchant_thumb_url": "",
            "aw_deep_link": "https://awin.test/2",
            "merchant_deep_link": "https://merchant.test/2",
            "brand_name": "Armani",
            "ean": "",
            "product_GTIN": "",
            "upc": "",
            "mpn": "",
            "in_stock": "1",
            "stock_quantity": "3",
            "stock_status": "in stock",
            "delivery_cost": "0",
            "data_feed_id": "97867",
            "merchant_name": "Example Merchant",
            "merchant_id": "105475",
            "category_id": "12",
            "product_type": "Perfume",
            "keywords": "fragrance",
            "specifications": "spray",
        },
        {
            "aw_product_id": "3",
            "merchant_product_id": "sku-3",
            "product_name": "Acme Secret Bloom 50 ml",
            "description": "Unknown fragrance",
            "category_name": "Fragrance",
            "merchant_category": "Fragrance",
            "search_price": "49.90",
            "display_price": "49.90",
            "store_price": "",
            "currency": "EUR",
            "merchant_image_url": "https://merchant.test/image-3.jpg",
            "large_image": "",
            "aw_image_url": "",
            "merchant_thumb_url": "",
            "aw_deep_link": "https://awin.test/3",
            "merchant_deep_link": "https://merchant.test/3",
            "brand_name": "Acme",
            "ean": "",
            "product_GTIN": "",
            "upc": "",
            "mpn": "",
            "in_stock": "1",
            "stock_quantity": "3",
            "stock_status": "in stock",
            "delivery_cost": "0",
            "data_feed_id": "97867",
            "merchant_name": "Example Merchant",
            "merchant_id": "105475",
            "category_id": "12",
            "product_type": "Perfume",
            "keywords": "fragrance",
            "specifications": "spray",
        },
        {
            "aw_product_id": "4",
            "merchant_product_id": "sku-4",
            "product_name": "Dior Sauvage Coffret EDT 2 x 50 ml",
            "description": "Gift set",
            "category_name": "Fragrance",
            "merchant_category": "Fragrance",
            "search_price": "120.00",
            "display_price": "120.00",
            "store_price": "",
            "currency": "EUR",
            "merchant_image_url": "https://merchant.test/image-4.jpg",
            "large_image": "",
            "aw_image_url": "",
            "merchant_thumb_url": "",
            "aw_deep_link": "https://awin.test/4",
            "merchant_deep_link": "https://merchant.test/4",
            "brand_name": "Dior",
            "ean": "",
            "product_GTIN": "",
            "upc": "",
            "mpn": "",
            "in_stock": "1",
            "stock_quantity": "3",
            "stock_status": "in stock",
            "delivery_cost": "0",
            "data_feed_id": "97867",
            "merchant_name": "Example Merchant",
            "merchant_id": "105475",
            "category_id": "12",
            "product_type": "Perfume",
            "keywords": "coffret edt",
            "specifications": "gift set",
        },
        {
            "aw_product_id": "5",
            "merchant_product_id": "sku-5",
            "product_name": "Chanel Coco Mademoiselle Body Lotion 200 ml",
            "description": "Body lotion",
            "category_name": "Fragrance",
            "merchant_category": "Fragrance",
            "search_price": "55.00",
            "display_price": "55.00",
            "store_price": "",
            "currency": "EUR",
            "merchant_image_url": "https://merchant.test/image-5.jpg",
            "large_image": "",
            "aw_image_url": "",
            "merchant_thumb_url": "",
            "aw_deep_link": "https://awin.test/5",
            "merchant_deep_link": "https://merchant.test/5",
            "brand_name": "Chanel",
            "ean": "",
            "product_GTIN": "",
            "upc": "",
            "mpn": "",
            "in_stock": "1",
            "stock_quantity": "3",
            "stock_status": "in stock",
            "delivery_cost": "0",
            "data_feed_id": "97867",
            "merchant_name": "Example Merchant",
            "merchant_id": "105475",
            "category_id": "12",
            "product_type": "Body Care",
            "keywords": "body lotion",
            "specifications": "lotion",
        },
    ]


def prepare_candidate_database(
    tmp_path: Path,
    *,
    advertiser_id: str = "105475",
    feed_id: str = "97867",
    rows: list[dict[str, str]] | None = None,
) -> tuple[Settings, str]:
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
        perfume_rows = [
            (str(uuid4()), "la-vie-est-belle", "La Vie Est Belle", "Lancome"),
            (str(uuid4()), "my-way", "My Way", "Armani"),
            (str(uuid4()), "sauvage", "Sauvage", "Dior"),
        ]
        for perfume_id, slug, name, brand in perfume_rows:
            conn.execute(
                """
                insert into perfumes (id, slug, name, brand)
                values (%s, %s, %s, %s)
                """,
                (perfume_id, slug, name, brand),
            )

    settings = build_settings(tmp_path, TEST_DATABASE_URL)
    DatabaseService(settings).migrate_db()

    if (advertiser_id, feed_id) != ("105475", "97867"):
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(
                """
                insert into advertisers (network, network_advertiser_id, name, currency, active)
                values ('awin', %s, %s, 'EUR', true)
                on conflict (network, network_advertiser_id) do nothing
                """,
                (advertiser_id, f"Advertiser {advertiser_id}"),
            )
            advertiser_db_id = conn.execute(
                """
                select id from advertisers
                where network = 'awin' and network_advertiser_id = %s
                """,
                (advertiser_id,),
            ).fetchone()[0]
            conn.execute(
                """
                insert into affiliate_feeds (
                    advertiser_id,
                    network,
                    network_feed_id,
                    language,
                    active
                )
                values (%s, 'awin', %s, 'fr_FR', true)
                on conflict (network, network_feed_id) do nothing
                """,
                (advertiser_db_id, feed_id),
            )

    csv_rows = rows or base_rows()
    for row in csv_rows:
        row["merchant_id"] = advertiser_id
        row["data_feed_id"] = feed_id

    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text(build_csv(csv_rows), encoding="utf-8")
    RawStagingService(settings).import_local_csv(
        advertiser_id=advertiser_id,
        feed_id=feed_id,
        path=csv_path,
        dry_run=False,
    )
    NormalizationService(settings).normalize_feed(
        advertiser_id=advertiser_id,
        feed_id=feed_id,
        dry_run=False,
    )
    return settings, TEST_DATABASE_URL


def test_unmatched_fragrance_creates_candidate(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)

    report, _ = CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        pending = conn.execute(
            """
            select candidate_name, status, proposed_perfume_id
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["candidates_created"] >= 1
    assert pending == ("Acme Secret Bloom 50 ml", "pending", None)


def test_needs_review_fuzzy_match_creates_candidate_with_proposed_perfume(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)

    report, _ = CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, proposed_perfume_id, match_score
            from product_match_candidates
            where candidate_name = 'Armani My Waye 50 ml'
            """
        ).fetchone()

    assert report["candidates_needs_review"] >= 1
    assert row[0] == "needs_review"
    assert row[1] is not None
    assert row[2] is not None


def test_duplicate_run_is_idempotent(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)

    first_report, _ = service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )
    second_report, _ = service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        candidates = conn.execute("select count(*) from product_match_candidates").fetchone()[0]

    assert first_report["candidates_created"] >= 1
    assert second_report["candidates_created"] == 0
    assert second_report["candidates_unchanged"] >= 1
    assert candidates == first_report["candidates_created"]


def test_rejected_candidate_is_not_recreated_as_pending(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            update product_match_candidates
            set status = 'rejected_duplicate'
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        )

    report, _ = service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        status = conn.execute(
            """
            select status
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()[0]

    assert report["candidates_ignored_existing_status"] >= 1
    assert status == "rejected_duplicate"


def test_ignored_candidate_is_not_recreated_as_pending(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
        include_excluded=True,
    )

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            update product_match_candidates
            set status = 'ignored'
            where candidate_name = 'Armani My Waye 50 ml'
            """
        )

    report, _ = service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
        include_excluded=True,
    )

    with psycopg.connect(database_url) as conn:
        status = conn.execute(
            """
            select status
            from product_match_candidates
            where candidate_name = 'Armani My Waye 50 ml'
            """
        ).fetchone()[0]

    assert report["candidates_ignored_existing_status"] >= 1
    assert status == "ignored"


def test_accepted_candidate_is_not_overwritten(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            update product_match_candidates
            set status = 'accepted_existing_perfume'
            where candidate_name = 'Armani My Waye 50 ml'
            """
        )

    report, _ = service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        status = conn.execute(
            """
            select status
            from product_match_candidates
            where candidate_name = 'Armani My Waye 50 ml'
            """
        ).fetchone()[0]

    assert report["candidates_ignored_existing_status"] >= 1
    assert status == "accepted_existing_perfume"


def test_coffret_becomes_needs_review_candidate_not_offer(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)

    report, _ = CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, match_reason
            from product_match_candidates
            where candidate_name = 'Dior Sauvage Coffret EDT 2 x 50 ml'
            """
        ).fetchone()
        offers = conn.execute("select count(*) from offers").fetchone()[0]

    assert report["rows_excluded_considered"] >= 1
    assert row[0] == "needs_review"
    assert "excluded_set_or_bundle" in row[1]
    assert offers == 0


def test_body_product_becomes_rejected_when_excluded_are_included(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)

    report, _ = CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
        include_excluded=True,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status
            from product_match_candidates
            where candidate_name = 'Chanel Coco Mademoiselle Body Lotion 200 ml'
            """
        ).fetchone()

    assert report["candidates_rejected_not_perfume"] >= 1
    assert row[0] == "rejected_not_perfume"


def test_dry_run_does_not_insert_candidates(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)

    report, _ = CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        candidates = conn.execute("select count(*) from product_match_candidates").fetchone()[0]

    assert report["candidates_created"] >= 1
    assert candidates == 0


def test_no_writes_to_offers_mappings_perfumes_or_perfume_offers(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)

    CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
        include_excluded=True,
    )

    with psycopg.connect(database_url) as conn:
        offers = conn.execute("select count(*) from offers").fetchone()[0]
        mappings = conn.execute("select count(*) from external_product_mappings").fetchone()[0]
        perfumes = conn.execute("select count(*) from perfumes").fetchone()[0]
        perfume_offers = conn.execute("select count(*) from perfume_offers").fetchone()[0]

    assert offers == 0
    assert mappings == 0
    assert perfumes == 3
    assert perfume_offers == 0


def test_generic_advertiser_feed_parameters_are_supported(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(
        tmp_path,
        advertiser_id="555",
        feed_id="444",
        rows=[
            {
                **base_rows()[2],
                "aw_product_id": "42",
                "merchant_product_id": "sku-42",
            }
        ],
    )

    report, _ = CandidateService(settings).create_candidates(
        advertiser_id="555",
        feed_id="444",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        advertiser_id = conn.execute(
            """
            select id
            from advertisers
            where network = 'awin' and network_advertiser_id = '555'
            """
        ).fetchone()[0]
        candidate = conn.execute(
            """
            select advertiser_id, candidate_name
            from product_match_candidates
            """
        ).fetchone()

    assert report["advertiser_id"] == "555"
    assert candidate == (advertiser_id, "Acme Secret Bloom 50 ml")
