from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.candidates import CandidateError, CandidateService
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


def create_perfume_insert_candidates_table(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            create table if not exists perfume_insert_candidates (
                id bigserial primary key,
                source_candidate_id bigint,
                source_offer_id bigint,
                candidate_brand text,
                candidate_name text not null,
                candidate_concentration text,
                candidate_volume_ml numeric(8, 2),
                candidate_category text,
                candidate_ean text,
                candidate_gtin text,
                candidate_upc text,
                candidate_mpn text,
                candidate_image_url text,
                candidate_source_title text,
                candidate_affiliate_url text,
                classification text not null,
                confidence numeric(5, 4),
                duplicate_risk text,
                duplicate_reason text,
                nearest_perfume_id uuid references perfumes(id) on delete set null,
                nearest_perfume_brand text,
                nearest_perfume_name text,
                review_status text not null default 'pending',
                review_notes text,
                reviewed_at timestamptz,
                reviewed_by text,
                first_seen_at timestamptz not null default now(),
                last_seen_at timestamptz not null default now(),
                seen_count integer not null default 1,
                promoted_at timestamptz,
                promoted_perfume_id uuid references perfumes(id) on delete set null,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
        conn.execute(
            """
            create unique index if not exists idx_perfume_insert_candidates_source_candidate
            on perfume_insert_candidates(source_candidate_id)
            where source_candidate_id is not null
            """
        )


def insert_perfume(
    database_url: str,
    *,
    brand: str,
    name: str,
    slug: str,
) -> str:
    perfume_id = str(uuid4())
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            insert into perfumes (id, slug, name, brand)
            values (%s, %s, %s, %s)
            """,
            (perfume_id, slug, name, brand),
        )
    return perfume_id


def advertiser_db_id(database_url: str, advertiser_id: str = "105475") -> int:
    with psycopg.connect(database_url) as conn:
        return int(
            conn.execute(
                """
                select id
                from advertisers
                where network = 'awin' and network_advertiser_id = %s
                """,
                (advertiser_id,),
            ).fetchone()[0]
        )


def perfume_id_by_name(database_url: str, name: str) -> str:
    with psycopg.connect(database_url) as conn:
        return str(
            conn.execute(
                """
                select id
                from perfumes
                where name = %s
                order by id
                limit 1
                """,
                (name,),
            ).fetchone()[0]
        )


def insert_reviewed_candidate(
    database_url: str,
    *,
    advertiser_id: str = "105475",
    status: str = "accepted_existing_perfume",
    proposed_perfume_id: str | None,
    candidate_brand: str = "Lancome",
    candidate_name: str = "La Vie Est Belle Eau de Parfum 50 ml",
    network_product_id: str | None = "aw-1",
    merchant_product_id: str | None = "sku-1",
    affiliate_url: str | None = "https://awin.test/reviewed-1",
    merchant_url: str | None = "https://merchant.test/reviewed-1",
    image_url: str | None = "https://merchant.test/reviewed-1.jpg",
    price: str | None = "79.90",
    currency: str | None = "EUR",
    ean: str | None = "111",
    mpn: str | None = "LVB-50",
    match_score: Decimal | None = None,
    match_reason: str = "Manual review accepted.",
    dedupe_key: str | None = None,
) -> int:
    if match_score is None:
        match_score = Decimal("97.00")

    enrichment_payload = {
        "network": "awin",
        "network_feed_id": "97867",
        "network_product_id": network_product_id,
        "merchant_product_id": merchant_product_id,
        "affiliate_url": affiliate_url,
        "merchant_url": merchant_url,
        "image_url": image_url,
        "price": price,
        "currency": currency,
        "title": candidate_name,
        "description": f"{candidate_name} description",
        "ean": ean,
        "mpn": mpn,
        "delivery_cost": "0",
        "match_method": "reviewed_candidate",
        "raw_payload": {
            "title": candidate_name,
            "affiliate_url": affiliate_url,
            "merchant_product_id": merchant_product_id,
            "network_product_id": network_product_id,
        },
    }
    with psycopg.connect(database_url, autocommit=True) as conn:
        candidate_id = conn.execute(
            """
            insert into product_match_candidates (
                advertiser_id,
                raw_feed_item_id,
                candidate_brand,
                candidate_name,
                candidate_concentration,
                candidate_volume_ml,
                candidate_category,
                candidate_image_url,
                candidate_url,
                proposed_perfume_id,
                match_score,
                match_reason,
                status,
                source_count,
                advertiser_count,
                enrichment_payload,
                dedupe_key
            )
            values (
                %s, %s, %s, %s, 'edp', 50.00, 'Fragrance', %s, %s, %s, %s, %s, %s, 1, 1, %s, %s
            )
            returning id
            """,
            (
                advertiser_db_id(database_url, advertiser_id),
                9000,
                candidate_brand,
                candidate_name,
                image_url,
                affiliate_url,
                proposed_perfume_id,
                match_score,
                match_reason,
                status,
                Jsonb(enrichment_payload),
                dedupe_key or f"reviewed-{uuid4()}",
            ),
        ).fetchone()[0]
    return int(candidate_id)


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


def test_sync_insert_candidates_creates_safe_candidate_and_tracking_fields(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    create_perfume_insert_candidates_table(database_url)
    CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    report, report_path = CandidateService(settings).sync_perfume_insert_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select classification, review_status, seen_count, first_seen_at, last_seen_at
            from perfume_insert_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["status"] == "success"
    assert report["staging_inserted"] >= 1
    assert report_path.exists()
    assert row[0] == "SAFE_INSERT_CANDIDATE"
    assert row[1] == "pending"
    assert row[2] == 1
    assert row[3] is not None
    assert row[4] is not None


def test_sync_insert_candidates_preserves_manual_review_status(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    create_perfume_insert_candidates_table(database_url)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    with psycopg.connect(database_url) as conn:
        candidate = conn.execute(
            """
            select id
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()
        conn.execute(
            """
            insert into perfume_insert_candidates (
                source_candidate_id,
                candidate_brand,
                candidate_name,
                classification,
                review_status,
                seen_count
            )
            values (%s, 'Acme', 'Curated Name', 'NEEDS_MANUAL_REVIEW', 'approved', 4)
            """,
            (candidate[0],),
        )

    report, _ = service.sync_perfume_insert_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select candidate_name, classification, review_status, seen_count
            from perfume_insert_candidates
            where source_candidate_id = (
                select id
                from product_match_candidates
                where candidate_name = 'Acme Secret Bloom 50 ml'
            )
            """
        ).fetchone()

    assert report["staging_ignored_manual_status"] >= 1
    assert row == ("Curated Name", "NEEDS_MANUAL_REVIEW", "approved", 5)


def test_sync_insert_candidates_increments_seen_count_for_pending_rows(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    create_perfume_insert_candidates_table(database_url)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    previous_time = datetime.now(timezone.utc) - timedelta(days=2)
    with psycopg.connect(database_url) as conn:
        candidate = conn.execute(
            """
            select id
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()
        conn.execute(
            """
            insert into perfume_insert_candidates (
                source_candidate_id,
                candidate_brand,
                candidate_name,
                classification,
                review_status,
                seen_count,
                first_seen_at,
                last_seen_at
            )
            values (
                %s,
                'Acme',
                'Acme Secret Bloom 50 ml',
                'NEEDS_MANUAL_REVIEW',
                'pending',
                2,
                %s,
                %s
            )
            """,
            (candidate[0], previous_time, previous_time),
        )

    report, _ = service.sync_perfume_insert_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select classification, seen_count, first_seen_at, last_seen_at
            from perfume_insert_candidates
            where source_candidate_id = (
                select id
                from product_match_candidates
                where candidate_name = 'Acme Secret Bloom 50 ml'
            )
            """
        ).fetchone()

    assert report["staging_updated"] >= 1
    assert report["staging_pending_refreshed"] >= 1
    assert row[0] == "SAFE_INSERT_CANDIDATE"
    assert row[1] == 3
    assert row[2] == previous_time
    assert row[3] > previous_time


def test_sync_insert_candidates_dry_run_does_not_write_staging_table(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    create_perfume_insert_candidates_table(database_url)
    CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    report, _ = CandidateService(settings).sync_perfume_insert_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    with psycopg.connect(database_url) as conn:
        count = conn.execute(
            "select count(*) from perfume_insert_candidates"
        ).fetchone()[0]

    assert report["staging_inserted"] >= 1
    assert count == 0


def test_sync_insert_candidates_classifies_non_perfume_and_ignores_promoted(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    create_perfume_insert_candidates_table(database_url)
    advertiser_id_value = advertiser_db_id(database_url)
    service = CandidateService(settings)

    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            insert into product_match_candidates (
                advertiser_id,
                candidate_brand,
                candidate_name,
                candidate_category,
                candidate_url,
                status,
                enrichment_payload,
                dedupe_key
            )
            values (
                %s,
                'Acme',
                'Acme Home Fragrance Candle 100 ml',
                'Home fragrance',
                'https://merchant.test/home',
                'pending',
                '{"network_feed_id": "97867", "title": "Acme Home Fragrance Candle 100 ml"}'::jsonb,
                'sync-home-fragrance'
            )
            returning id
            """,
            (advertiser_id_value,),
        ).fetchone()[0]
        promoted_source_candidate_id = conn.execute(
            """
            insert into product_match_candidates (
                advertiser_id,
                candidate_brand,
                candidate_name,
                candidate_url,
                status,
                enrichment_payload,
                dedupe_key
            )
            values (
                %s,
                'Montale',
                'Montale Bubble Forever 100 ml',
                'https://merchant.test/montale',
                'pending',
                '{"network_feed_id": "97867", "title": "Montale Bubble Forever 100 ml"}'::jsonb,
                'sync-promoted'
            )
            returning id
            """,
            (advertiser_id_value,),
        ).fetchone()[0]
        conn.execute(
            """
            insert into perfume_insert_candidates (
                source_candidate_id,
                candidate_brand,
                candidate_name,
                classification,
                review_status,
                seen_count
            )
            values (
                %s,
                'Montale',
                'Montale Bubble Forever 100 ml',
                'SAFE_INSERT_CANDIDATE',
                'promoted',
                9
            )
            """,
            (promoted_source_candidate_id,),
        )

    report, _ = service.sync_perfume_insert_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        non_perfume = conn.execute(
            """
            select classification, duplicate_risk
            from perfume_insert_candidates
            where source_candidate_id = (
                select id
                from product_match_candidates
                where candidate_name = 'Acme Home Fragrance Candle 100 ml'
            )
            """
        ).fetchone()
        promoted = conn.execute(
            """
            select review_status, seen_count
            from perfume_insert_candidates
            where source_candidate_id = %s
            """,
            (promoted_source_candidate_id,),
        ).fetchone()

    assert report["staging_ignored_manual_status"] >= 1
    assert non_perfume == ("NON_PERFUME_PRODUCT", None)
    assert promoted == ("promoted", 10)


def test_sync_insert_candidates_safe_duplicate_risk_stays_db_compatible(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    create_perfume_insert_candidates_table(database_url)
    CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    CandidateService(settings).sync_perfume_insert_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select classification, duplicate_risk
            from perfume_insert_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert row == ("SAFE_INSERT_CANDIDATE", "low")


def test_refresh_product_match_candidates_dry_run_does_not_write(tmp_path: Path) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )
    expected_perfume_id = insert_perfume(
        database_url,
        brand="Acme",
        name="Acme Secret Bloom 50 ml",
        slug="acme-secret-bloom",
    )

    report, report_path = CandidateService(settings).refresh_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, proposed_perfume_id
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["status"] == "success"
    assert report["candidates_updated"] >= 1
    assert report_path.exists()
    assert row == ("pending", None)
    assert expected_perfume_id is not None


def test_refresh_product_match_candidates_updates_pending_candidate(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    CandidateService(settings).create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )
    perfume_id = insert_perfume(
        database_url,
        brand="Acme",
        name="Acme Secret Bloom 50 ml",
        slug="acme-secret-bloom",
    )

    report, _ = CandidateService(settings).refresh_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, proposed_perfume_id, match_score
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["candidates_updated"] >= 1
    assert row[0] == "needs_review"
    assert str(row[1]) == perfume_id
    assert row[2] is not None


def test_refresh_product_match_candidates_updates_needs_review_candidate(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )
    perfume_id = insert_perfume(
        database_url,
        brand="Acme",
        name="Acme Secret Bloom 50 ml",
        slug="acme-secret-bloom",
    )
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            update product_match_candidates
            set status = 'needs_review',
                match_score = 10,
                match_reason = 'Old weak match.'
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        )

    report, _ = service.refresh_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, proposed_perfume_id, match_score, match_reason
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["candidates_updated"] >= 1
    assert row[0] == "needs_review"
    assert str(row[1]) == perfume_id
    assert row[2] > 10
    assert "Matched" in row[3]


def test_refresh_product_match_candidates_ignores_closed_statuses(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )
    insert_perfume(
        database_url,
        brand="Acme",
        name="Acme Secret Bloom 50 ml",
        slug="acme-secret-bloom",
    )
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            update product_match_candidates
            set status = 'accepted_new_perfume'
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        )

    report, _ = service.refresh_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        only_statuses=["accepted_new_perfume"],
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, proposed_perfume_id
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["candidates_ignored_closed_status"] >= 1
    assert row == ("accepted_new_perfume", None)


def test_refresh_product_match_candidates_brand_filter(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )
    insert_perfume(
        database_url,
        brand="Acme",
        name="Acme Secret Bloom 50 ml",
        slug="acme-secret-bloom",
    )

    report, _ = service.refresh_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        brand="MONTALE",
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, proposed_perfume_id
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["candidates_loaded"] == 0
    assert row == ("pending", None)


def test_refresh_product_match_candidates_without_match_stays_unchanged(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    service.create_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        min_review_score=70,
    )

    report, report_path = service.refresh_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select status, proposed_perfume_id
            from product_match_candidates
            where candidate_name = 'Acme Secret Bloom 50 ml'
            """
        ).fetchone()

    assert report["candidates_without_match"] >= 1
    assert report_path.exists()
    assert row == ("pending", None)


def test_apply_reviewed_candidates_dry_run_does_not_write_offers(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    insert_reviewed_candidate(
        database_url,
        proposed_perfume_id=perfume_id_by_name(database_url, "La Vie Est Belle"),
    )

    report, report_path = CandidateService(settings).apply_reviewed_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    with psycopg.connect(database_url) as conn:
        offers = conn.execute("select count(*) from offers").fetchone()[0]

    assert report["offers_inserted"] == 1
    assert report["candidates_applied"] == 1
    assert report_path.exists()
    assert offers == 0


def test_apply_reviewed_candidates_needs_review_ignored_by_default(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    insert_reviewed_candidate(
        database_url,
        status="needs_review",
        proposed_perfume_id=perfume_id_by_name(database_url, "La Vie Est Belle"),
    )

    report, _ = CandidateService(settings).apply_reviewed_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert report["candidates_loaded"] == 0
    assert report["offers_inserted"] == 0


def test_apply_reviewed_candidates_needs_review_requires_allow_flag(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    insert_reviewed_candidate(
        database_url,
        status="needs_review",
        proposed_perfume_id=perfume_id_by_name(database_url, "La Vie Est Belle"),
    )

    with pytest.raises(CandidateError, match="allow-needs-review"):
        CandidateService(settings).apply_reviewed_product_match_candidates(
            advertiser_id="105475",
            feed_id="97867",
            dry_run=True,
            statuses=["needs_review"],
        )


def test_apply_reviewed_candidates_needs_review_allowed_creates_offer(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    perfume_id = perfume_id_by_name(database_url, "La Vie Est Belle")
    insert_reviewed_candidate(
        database_url,
        status="needs_review",
        proposed_perfume_id=perfume_id,
        network_product_id="aw-needs-review",
        merchant_product_id="sku-needs-review",
    )

    report, _ = CandidateService(settings).apply_reviewed_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
        statuses=["needs_review"],
        allow_needs_review=True,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select perfume_id, match_status, match_method
            from offers
            where network_product_id = 'aw-needs-review'
            """
        ).fetchone()

    assert report["offers_inserted"] == 1
    assert str(row[0]) == perfume_id
    assert row[1] == "matched_reviewed_candidate"
    assert row[2] == "reviewed_candidate"


def test_apply_reviewed_candidates_upserts_existing_offer(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    service = CandidateService(settings)
    candidate_id = insert_reviewed_candidate(
        database_url,
        proposed_perfume_id=perfume_id_by_name(database_url, "La Vie Est Belle"),
        network_product_id="aw-upsert",
        merchant_product_id="sku-upsert",
    )

    first_report, _ = service.apply_reviewed_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url, autocommit=True) as conn:
        enrichment = conn.execute(
            """
            select enrichment_payload
            from product_match_candidates
            where id = %s
            """,
            (candidate_id,),
        ).fetchone()[0]
        payload = dict(enrichment)
        payload["price"] = "89.90"
        conn.execute(
            """
            update product_match_candidates
            set enrichment_payload = %s,
                match_score = 99.00
            where id = %s
            """,
            (Jsonb(payload), candidate_id),
        )

    second_report, _ = service.apply_reviewed_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            select price, metadata ->> 'source'
            from offers
            where network_product_id = 'aw-upsert'
            """
        ).fetchone()

    assert first_report["offers_inserted"] == 1
    assert second_report["offers_updated"] == 1
    assert row == (Decimal("89.90"), "reviewed_candidate")


def test_apply_reviewed_candidates_skips_missing_external_id(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    insert_reviewed_candidate(
        database_url,
        proposed_perfume_id=perfume_id_by_name(database_url, "La Vie Est Belle"),
        network_product_id=None,
        merchant_product_id=None,
    )

    report, _ = CandidateService(settings).apply_reviewed_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        offers = conn.execute("select count(*) from offers").fetchone()[0]

    assert report["skipped_missing_external_id"] == 1
    assert offers == 0


def test_apply_reviewed_candidates_skips_missing_payload_and_does_not_touch_perfumes(
    tmp_path: Path,
) -> None:
    settings, database_url = prepare_candidate_database(tmp_path)
    insert_reviewed_candidate(
        database_url,
        proposed_perfume_id=perfume_id_by_name(database_url, "La Vie Est Belle"),
        affiliate_url=None,
        price=None,
    )

    with psycopg.connect(database_url) as conn:
        perfumes_before = conn.execute("select count(*) from perfumes").fetchone()[0]

    report, _ = CandidateService(settings).apply_reviewed_product_match_candidates(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    with psycopg.connect(database_url) as conn:
        offers = conn.execute("select count(*) from offers").fetchone()[0]
        perfumes_after = conn.execute("select count(*) from perfumes").fetchone()[0]

    assert report["skipped_missing_payload"] == 1
    assert offers == 0
    assert perfumes_before == perfumes_after
