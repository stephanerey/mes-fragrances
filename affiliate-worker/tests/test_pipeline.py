from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.config import Settings
from app.db import DatabaseService
from app.pipeline import PIPELINE_LATEST_REPORT_NAME, PipelineService

TEST_DATABASE_URL = os.getenv("AFFILIATE_TEST_DATABASE_URL")


def build_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "AFFILIATE_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": database_url,
        }
    )


def prepare_pipeline_database(
    tmp_path: Path,
    *,
    extra_feeds: list[tuple[str, str]] | None = None,
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
        conn.execute(
            """
            insert into perfumes (id, slug, name, brand)
            values (%s, %s, %s, %s)
            """,
            (uuid4(), "test-perfume", "Test Perfume", "Test Brand"),
        )

    settings = build_settings(tmp_path, TEST_DATABASE_URL)
    DatabaseService(settings).migrate_db()

    if extra_feeds:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            for advertiser_id, feed_id in extra_feeds:
                conn.execute(
                    """
                    insert into advertisers (
                        network,
                        network_advertiser_id,
                        name,
                        currency,
                        active
                    )
                    values ('awin', %s, %s, 'EUR', true)
                    on conflict (network, network_advertiser_id) do nothing
                    """,
                    (advertiser_id, f"Advertiser {advertiser_id}"),
                )
                advertiser_db_id = conn.execute(
                    """
                    select id
                    from advertisers
                    where network = 'awin'
                      and network_advertiser_id = %s
                    """,
                    (advertiser_id,),
                ).fetchone()[0]
                conn.execute(
                    """
                    insert into affiliate_feeds (
                        advertiser_id,
                        network,
                        network_feed_id,
                        feed_name,
                        active,
                        metadata
                    )
                    values (%s, 'awin', %s, %s, true, '{}'::jsonb)
                    on conflict (network, network_feed_id) do nothing
                    """,
                    (advertiser_db_id, feed_id, f"Feed {feed_id}"),
                )

    return settings, TEST_DATABASE_URL


class DummyRawStagingService:
    def __init__(
        self,
        reports_dir: Path,
        fail_for: set[tuple[str, str]] | None = None,
        *,
        rows_total: int = 5,
        rows_inserted_non_dry_run: int = 5,
        rows_duplicates_non_dry_run: int = 0,
    ) -> None:
        self.reports_dir = reports_dir
        self.fail_for = fail_for or set()
        self.rows_total = rows_total
        self.rows_inserted_non_dry_run = rows_inserted_non_dry_run
        self.rows_duplicates_non_dry_run = rows_duplicates_non_dry_run
        self.calls: list[tuple[str, str, str, bool]] = []

    def import_remote_feed(
        self,
        *,
        network: str,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
    ) -> tuple[dict[str, object], Path]:
        self.calls.append((network, advertiser_id, feed_id, dry_run))
        if (advertiser_id, feed_id) in self.fail_for:
            raise RuntimeError(f"raw import failed for {advertiser_id}/{feed_id}")
        report = {
            "status": "success",
            "rows_total": self.rows_total,
            "rows_inserted": 0 if dry_run else self.rows_inserted_non_dry_run,
            "rows_duplicates": 0 if dry_run else self.rows_duplicates_non_dry_run,
            "rows_errors": 0,
        }
        path = self.reports_dir / f"raw_{advertiser_id}_{feed_id}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return report, path


class DummyNormalizationService:
    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.calls: list[tuple[str, str, bool]] = []

    def normalize_feed(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
        import_run_id: int | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, object], Path]:
        self.calls.append((advertiser_id, feed_id, dry_run))
        report = {
            "status": "success",
            "raw_rows_total": 5,
            "normalized_rows_inserted": 0 if dry_run else 5,
            "rows_fragrance": 5,
            "rows_excluded": 1,
        }
        path = self.reports_dir / f"normalize_{advertiser_id}_{feed_id}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return report, path


class DummyMatchingService:
    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.calls: list[tuple[str, str, bool, bool]] = []

    def match_offers(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
        limit: int | None = None,
        min_score: int | None = None,
        disable_fuzzy: bool = False,
        no_stale_update: bool = False,
    ) -> tuple[dict[str, object], Path]:
        self.calls.append((advertiser_id, feed_id, dry_run, no_stale_update))
        report = {
            "status": "success",
            "offers_inserted": 0 if dry_run else 1,
            "offers_updated": 0,
            "offers_unchanged": 3,
            "offers_price_changed": 0,
            "stale_offers_incremented": 0,
            "stale_offers_deactivated": 0,
        }
        path = self.reports_dir / f"match_{advertiser_id}_{feed_id}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return report, path


class DummyCandidateService:
    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.calls: list[tuple[str, str, bool]] = []

    def create_candidates(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
        limit: int | None = None,
        include_excluded: bool = False,
        disable_fuzzy: bool = False,
        min_review_score: int | None = None,
    ) -> tuple[dict[str, object], Path]:
        self.calls.append((advertiser_id, feed_id, dry_run))
        report = {
            "status": "success",
            "candidates_created": 2,
            "candidates_updated": 0,
            "candidates_unchanged": 4,
        }
        path = self.reports_dir / f"candidates_{advertiser_id}_{feed_id}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return report, path


def build_pipeline_service(
    settings: Settings,
    *,
    fail_raw_for: set[tuple[str, str]] | None = None,
    rows_total: int = 5,
    rows_inserted_non_dry_run: int = 5,
    rows_duplicates_non_dry_run: int = 0,
) -> tuple[
    PipelineService,
    DummyRawStagingService,
    DummyNormalizationService,
    DummyMatchingService,
    DummyCandidateService,
]:
    reports_dir = settings.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    raw = DummyRawStagingService(
        reports_dir,
        fail_for=fail_raw_for,
        rows_total=rows_total,
        rows_inserted_non_dry_run=rows_inserted_non_dry_run,
        rows_duplicates_non_dry_run=rows_duplicates_non_dry_run,
    )
    normalization = DummyNormalizationService(reports_dir)
    matching = DummyMatchingService(reports_dir)
    candidates = DummyCandidateService(reports_dir)
    service = PipelineService(
        settings,
        raw_staging_service=raw,
        normalization_service=normalization,
        matching_service=matching,
        candidate_service=candidates,
        sleep_func=lambda _: None,
        randint_func=lambda low, high: high,
    )
    return service, raw, normalization, matching, candidates


def test_pipeline_dry_run_writes_aggregate_and_latest_report(tmp_path: Path) -> None:
    settings, database_url = prepare_pipeline_database(tmp_path)
    service, raw, normalization, matching, candidates = build_pipeline_service(settings)

    result = service.run_pipeline(
        network="awin",
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert result.exit_code == 0
    assert result.report["status"] == "success"
    assert result.report["lock_acquired"] is True
    assert result.report["feeds_total"] == 1
    assert result.report["totals"]["raw_rows_total"] == 5
    assert result.report["totals"]["raw_rows_inserted"] == 0
    assert result.report["totals"]["normalized_rows_total"] == 5
    assert result.report["totals"]["normalized_rows_inserted"] == 0
    assert result.report["totals"]["offers_inserted"] == 0
    assert result.report["totals"]["candidates_created"] == 0
    assert raw.calls == [("awin", "105475", "97867", True)]
    assert normalization.calls == [("105475", "97867", True)]
    assert matching.calls == [("105475", "97867", True, True)]
    assert candidates.calls == [("105475", "97867", True)]

    latest_report = settings.reports_dir / PIPELINE_LATEST_REPORT_NAME
    assert result.report_path.exists()
    assert latest_report.exists()
    assert json.loads(result.report_path.read_text(encoding="utf-8")) == json.loads(
        latest_report.read_text(encoding="utf-8")
    )
    assert database_url not in result.report_path.read_text(encoding="utf-8")
    assert result.report_path.name.startswith("affiliate_pipeline_")

    with psycopg.connect(database_url) as conn:
        counts = conn.execute(
            """
            select
                (select count(*) from feed_import_runs) as import_runs,
                (select count(*) from offers) as offers_count,
                (select count(*) from product_match_candidates) as candidates_count
            """
        ).fetchone()
    assert counts[0] == 0
    assert counts[1] == 0
    assert counts[2] == 0


def test_pipeline_discovers_active_feeds_generically(tmp_path: Path) -> None:
    settings, _ = prepare_pipeline_database(
        tmp_path,
        extra_feeds=[("999001", "200001"), ("999002", "200002")],
    )
    service, raw, normalization, matching, candidates = build_pipeline_service(settings)

    result = service.run_pipeline(network="awin", dry_run=True)

    assert result.exit_code == 0
    assert result.report["feeds_total"] == 3
    assert raw.calls == [
        ("awin", "105475", "97867", True),
        ("awin", "999001", "200001", True),
        ("awin", "999002", "200002", True),
    ]
    assert [call[:2] for call in normalization.calls] == [
        ("105475", "97867"),
        ("999001", "200001"),
        ("999002", "200002"),
    ]
    assert len(matching.calls) == 3
    assert len(candidates.calls) == 3


def test_pipeline_skips_when_lock_is_already_held(tmp_path: Path) -> None:
    settings, _ = prepare_pipeline_database(tmp_path)
    service, raw, normalization, matching, candidates = build_pipeline_service(settings)

    with service.db_service.connect(autocommit=True) as conn:
        assert service._try_acquire_pipeline_lock(conn, network="awin") is True
        result = service.run_pipeline(
            network="awin",
            advertiser_id="105475",
            feed_id="97867",
            dry_run=True,
        )

    assert result.exit_code == 2
    assert result.report["status"] == "skipped_locked"
    assert result.report["lock_acquired"] is False
    assert raw.calls == []
    assert normalization.calls == []
    assert matching.calls == []
    assert candidates.calls == []


def test_pipeline_raw_import_failure_skips_downstream_and_returns_non_zero(
    tmp_path: Path,
) -> None:
    settings, _ = prepare_pipeline_database(tmp_path)
    service, raw, normalization, matching, candidates = build_pipeline_service(
        settings,
        fail_raw_for={("105475", "97867")},
    )

    result = service.run_pipeline(
        network="awin",
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    assert result.exit_code == 1
    assert result.report["status"] == "failed"
    assert result.report["feeds_failed"] == 1
    feed_result = result.report["feeds"][0]
    assert feed_result["steps"]["raw_import"]["status"] == "failed"
    assert feed_result["steps"]["normalization"]["status"] == "skipped"
    assert feed_result["steps"]["matching"]["status"] == "skipped"
    assert feed_result["steps"]["candidates"]["status"] == "skipped"
    assert normalization.calls == []
    assert matching.calls == []
    assert candidates.calls == []
    assert result.report["totals"]["stale_offers_deactivated"] == 0
    assert result.report["totals"]["candidates_created"] == 0


def test_pipeline_disables_stale_updates_when_raw_import_is_not_full_snapshot(
    tmp_path: Path,
) -> None:
    settings, _ = prepare_pipeline_database(tmp_path)
    service, raw, normalization, matching, candidates = build_pipeline_service(
        settings,
        rows_total=5,
        rows_inserted_non_dry_run=1,
        rows_duplicates_non_dry_run=4,
    )

    result = service.run_pipeline(
        network="awin",
        advertiser_id="105475",
        feed_id="97867",
        dry_run=False,
    )

    assert result.exit_code == 0
    assert raw.calls == [("awin", "105475", "97867", False)]
    assert normalization.calls == [("105475", "97867", False)]
    assert matching.calls == [("105475", "97867", False, True)]
    assert candidates.calls == [("105475", "97867", False)]
    assert "Stale offer update skipped" in result.report["feeds"][0]["warnings"][0]
