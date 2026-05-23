from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.config import Settings
from app.db import (
    AFFILIATE_TABLES,
    TRACKING_TABLE,
    DatabaseService,
    load_migrations,
    normalize_database_url,
    plan_migrations,
    select_candidate_catalog_tables,
    select_candidate_offer_tables,
)

TEST_DATABASE_URL = os.getenv("AFFILIATE_TEST_DATABASE_URL")


def build_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "AFFILIATE_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": database_url,
        }
    )


def test_load_migrations_orders_files(tmp_path: Path) -> None:
    (tmp_path / "0002_second.sql").write_text("select 2;\n", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text("select 1;\n", encoding="utf-8")

    migrations = load_migrations(tmp_path)

    assert [migration.version for migration in migrations] == ["0001", "0002"]
    assert [migration.name for migration in migrations] == ["first", "second"]


def test_plan_migrations_marks_pending_and_applied(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("select 1;\n", encoding="utf-8")
    (tmp_path / "0002_second.sql").write_text("select 2;\n", encoding="utf-8")

    migrations = load_migrations(tmp_path)
    plan = plan_migrations(migrations, {"0001"})

    assert plan == [
        {
            "version": "0001",
            "name": "first",
            "filename": "0001_first.sql",
            "checksum": migrations[0].checksum,
            "applied": True,
            "pending": False,
        },
        {
            "version": "0002",
            "name": "second",
            "filename": "0002_second.sql",
            "checksum": migrations[1].checksum,
            "applied": False,
            "pending": True,
        },
    ]


def test_select_candidate_tables_from_columns() -> None:
    columns_by_table = {
        "perfumes": [
            {"column_name": "id"},
            {"column_name": "slug"},
            {"column_name": "name"},
            {"column_name": "brand"},
        ],
        "perfume_offers": [
            {"column_name": "price"},
            {"column_name": "affiliate_url"},
        ],
        "users": [{"column_name": "id"}, {"column_name": "email"}],
    }

    assert select_candidate_catalog_tables(columns_by_table) == ["perfumes"]
    assert select_candidate_offer_tables(columns_by_table) == ["perfume_offers"]


def test_normalize_database_url_accepts_sqlalchemy_style_prefix() -> None:
    assert (
        normalize_database_url("postgresql+psycopg://user:pass@db:5432/pilot")
        == "postgresql://user:pass@db:5432/pilot"
    )


@pytest.fixture()
def postgres_database(tmp_path: Path) -> tuple[Settings, str]:
    if not TEST_DATABASE_URL:
        pytest.skip("AFFILIATE_TEST_DATABASE_URL is not configured")

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
        conn.execute(
            """
            create table alembic_version (
                version_num varchar(32) primary key
            )
            """
        )
        conn.execute(
            """
            create table perfumes (
                id uuid primary key,
                slug varchar not null,
                name varchar not null,
                brand varchar not null,
                image_url varchar,
                short_description text,
                description text,
                olfactive_family varchar,
                budget_tier varchar,
                top_notes jsonb not null default '[]'::jsonb,
                heart_notes jsonb not null default '[]'::jsonb,
                base_notes jsonb not null default '[]'::jsonb,
                quiz_tags jsonb not null default '[]'::jsonb,
                is_new_arrival boolean not null default false,
                is_best_seller boolean not null default false,
                is_published boolean not null default true,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now(),
                gender varchar,
                source_price numeric
            )
            """
        )
        conn.execute(
            """
            create unique index ix_perfumes_slug
                on perfumes(slug)
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
                availability varchar,
                affiliate_url text not null,
                is_active boolean not null default true,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
        conn.execute(
            """
            create index ix_perfume_offers_perfume_id
                on perfume_offers(perfume_id)
            """
        )
        conn.execute(
            """
            insert into perfumes (id, slug, name, brand)
            values (%s, %s, %s, %s)
            """,
            (uuid4(), "test-perfume", "Test Perfume", "Test Brand"),
        )

    return build_settings(tmp_path, TEST_DATABASE_URL), TEST_DATABASE_URL


def test_inspect_db_output_shape(postgres_database: tuple[Settings, str]) -> None:
    settings, _ = postgres_database

    report, report_path = DatabaseService(settings).inspect_db()

    assert report["status"] == "success"
    assert report["db_engine"] == "PostgreSQL"
    assert report["current_schema"] == "public"
    assert "perfumes" in report["public_tables"]
    assert "perfume_offers" in report["public_tables"]
    assert report["migration_tracking_table_exists"] is False
    assert report["candidate_catalog_tables"][0]["table_name"] == "perfumes"
    assert report["candidate_offer_tables"][0]["table_name"] == "perfume_offers"
    assert report_path.exists()


def test_migrate_db_is_idempotent_and_seeds_comas(
    postgres_database: tuple[Settings, str],
) -> None:
    settings, database_url = postgres_database
    service = DatabaseService(settings)

    dry_run_report, _ = service.migrate_db(dry_run=True)
    assert dry_run_report["status"] == "success"
    assert dry_run_report["pending_count"] == 4
    assert dry_run_report["migration_tracking_table_exists"] is False

    first_report, _ = service.migrate_db()
    assert first_report["status"] == "success"
    assert first_report["applied_count"] == 4
    assert all(first_report["affiliate_tables_exist"].values())

    second_report, _ = service.migrate_db()
    assert second_report["status"] == "success"
    assert second_report["applied_count"] == 0
    assert second_report["pending_count"] == 0

    with psycopg.connect(database_url) as conn:
        advertiser_row = conn.execute(
            """
            select name, currency, awin_feed_id
            from advertisers
            where network = 'awin' and network_advertiser_id = '105475'
            """
        ).fetchone()
        feed_row = conn.execute(
            """
            select language, download_url, metadata ->> 'expected_format' as expected_format
            from affiliate_feeds
            where network = 'awin' and network_feed_id = '97867'
            """
        ).fetchone()
        tracking_rows = conn.execute(
            f"select version from {TRACKING_TABLE} order by version"
        ).fetchall()
        raw_feed_item_indexes = conn.execute(
            """
            select indexname
            from pg_indexes
            where schemaname = 'public'
              and tablename = 'raw_feed_items'
            order by indexname
            """
        ).fetchall()
        normalized_feed_item_indexes = conn.execute(
            """
            select indexname
            from pg_indexes
            where schemaname = 'public'
              and tablename = 'normalized_feed_items'
            order by indexname
            """
        ).fetchall()
        candidate_indexes = conn.execute(
            """
            select indexname
            from pg_indexes
            where schemaname = 'public'
              and tablename = 'product_match_candidates'
            order by indexname
            """
        ).fetchall()
        existing_tables = conn.execute(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public'
              and table_name = any(%s)
            order by table_name
            """,
            ([*AFFILIATE_TABLES, TRACKING_TABLE],),
        ).fetchall()

    assert advertiser_row == ("Perfumerias Comas FR", "EUR", "97867")
    assert feed_row == ("fr_FR", None, "csv")
    assert [row[0] for row in tracking_rows] == ["0001", "0002", "0003", "0004"]
    assert "idx_raw_feed_items_advertiser_raw_hash" in [row[0] for row in raw_feed_item_indexes]
    assert "idx_normalized_feed_items_normalized_title" in [
        row[0] for row in normalized_feed_item_indexes
    ]
    assert "idx_product_match_candidates_advertiser_dedupe" in [
        row[0] for row in candidate_indexes
    ]
    assert [row[0] for row in existing_tables] == sorted([*AFFILIATE_TABLES, TRACKING_TABLE])
