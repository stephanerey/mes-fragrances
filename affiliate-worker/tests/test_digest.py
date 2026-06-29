from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import app.digest as digest_module
from app.config import Settings, get_settings
from app.digest import AffiliateDigestService, DigestError
from app.main import main


def build_settings(tmp_path: Path, *, database_url: str | None = None) -> Settings:
    payload: dict[str, object] = {"AFFILIATE_DATA_DIR": str(tmp_path / "data")}
    if database_url is not None:
        payload["DATABASE_URL"] = database_url
    return Settings.model_validate(payload)


class FakeCursor:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.executed: list[tuple[str, object]] = []
        self._current_result: object = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, query: str, params: object = None) -> None:
        self.executed.append((str(query), params))
        self._current_result = self._responses.pop(0) if self._responses else None

    def fetchone(self) -> tuple[object, ...]:
        assert isinstance(self._current_result, tuple)
        return self._current_result

    def fetchall(self) -> list[tuple[object, ...]]:
        assert isinstance(self._current_result, list)
        return self._current_result


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> FakeCursor:
        return self._cursor


def write_pipeline_report(
    reports_dir: Path,
    filename: str,
    *,
    started_at: str,
    finished_at: str,
    status: str,
    feeds: list[dict[str, object]],
    warnings: list[str] | None = None,
) -> Path:
    payload = {
        "command": "run-affiliate-pipeline",
        "dry_run": False,
        "duration_seconds": 12.0,
        "email_report": {"attempted": False, "success": False, "skipped": True},
        "feeds": feeds,
        "feeds_failed": sum(1 for feed in feeds if feed.get("status") != "success"),
        "feeds_skipped": 0,
        "feeds_succeeded": sum(1 for feed in feeds if feed.get("status") == "success"),
        "feeds_total": len(feeds),
        "filters": {},
        "finished_at": finished_at,
        "latest_import_run_id": 44,
        "lock_acquired": True,
        "lock_strategy": "postgres_advisory_lock",
        "network": "awin",
        "perfume_insert_candidates_counts": {"pending": 10, "promoted": 2},
        "random_delay_seconds": 0,
        "safe_top_brands": [],
        "started_at": started_at,
        "status": status,
        "totals": {},
        "warnings": warnings or [],
    }
    path = reports_dir / filename
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_feed(
    *,
    advertiser_id: str,
    advertiser_name: str,
    feed_id: str,
    status: str,
    offers_inserted: int = 0,
    offers_updated: int = 0,
    candidates_created: int = 0,
    candidates_updated: int = 0,
    safe_new_candidates_count: int = 0,
    refresh_candidates_would_update: int = 0,
    refresh_candidates_without_match: int = 0,
    warnings: list[str] | None = None,
    step_error: str | None = None,
) -> dict[str, object]:
    steps = {
        "raw_import": {"status": "success", "report_path": None},
        "candidate_sync": {"status": "success", "report_path": None},
        "refresh_dry_run": {"status": "success", "report_path": None},
    }
    if step_error is not None:
        steps["raw_import"] = {"status": "failed", "report_path": None, "error": step_error}
    return {
        "advertiser_db_id": 1,
        "advertiser_id": advertiser_id,
        "advertiser_name": advertiser_name,
        "affiliate_feed_db_id": 1,
        "feed_id": feed_id,
        "network": "awin",
        "status": status,
        "steps": steps,
        "summary": {
            "import_run_id": 44,
            "offers_inserted": offers_inserted,
            "offers_updated": offers_updated,
            "offers_unchanged": 0,
            "candidates_created": candidates_created,
            "candidates_updated": candidates_updated,
            "candidates_unchanged": 0,
            "safe_new_candidates_count": safe_new_candidates_count,
            "refresh_candidates_loaded": 10,
            "refresh_candidates_would_update": refresh_candidates_would_update,
            "refresh_candidates_without_match": refresh_candidates_without_match,
            "rows_errors": 0,
        },
        "warnings": warnings or [],
    }


def test_digest_service_generates_french_markdown_grouped_by_feed(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    reports_dir = settings.reports_dir
    reports_dir.mkdir(parents=True)
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)

    write_pipeline_report(
        reports_dir,
        "affiliate_pipeline_20260624_043137_awin.json",
        started_at="2026-06-24T04:31:37+00:00",
        finished_at="2026-06-24T04:31:50+00:00",
        status="success",
        warnings=[
            "Stale offer update skipped because the current raw import did not "
            "materialize a full snapshot for this feed."
        ],
        feeds=[
            build_feed(
                advertiser_id="105475",
                advertiser_name="Perfumerias Comas FR",
                feed_id="97867",
                status="success",
                offers_inserted=7,
                offers_updated=73,
                candidates_created=4,
                candidates_updated=103,
                refresh_candidates_would_update=68,
                refresh_candidates_without_match=1517,
            ),
            build_feed(
                advertiser_id="200001",
                advertiser_name="Flaconi FR",
                feed_id="12345",
                status="success",
                offers_inserted=2,
                offers_updated=15,
                candidates_created=1,
                candidates_updated=9,
                safe_new_candidates_count=1,
                refresh_candidates_would_update=21,
                refresh_candidates_without_match=100,
            ),
        ],
    )
    write_pipeline_report(
        reports_dir,
        "affiliate_pipeline_20260627_042320_awin.json",
        started_at="2026-06-27T04:23:20+00:00",
        finished_at="2026-06-27T04:23:33+00:00",
        status="failed",
        feeds=[
            build_feed(
                advertiser_id="200001",
                advertiser_name="Flaconi FR",
                feed_id="12345",
                status="failed",
                warnings=[
                    "Feed is empty and has no CSV header. Report written to "
                    "/data/reports/raw_stage_import_error.json"
                ],
                step_error=(
                    "Feed is empty and has no CSV header. Report written to "
                    "/data/reports/raw_stage_import_error.json"
                ),
            )
        ],
    )

    report, report_path = AffiliateDigestService(
        settings,
        now_fn=lambda: now,
    ).generate_digest(
        reports_root=reports_dir,
        since_days=7,
        locale="fr",
        output_dir=tmp_path / "out",
        email_subject=None,
        dry_run=True,
        send_email=False,
    )

    markdown_path = Path(report["markdown_report_path"])
    markdown = markdown_path.read_text(encoding="utf-8")
    assert report_path.exists()
    assert report["metrics"]["runs_total"] == 2
    assert report["metrics"]["runs_success"] == 1
    assert report["metrics"]["runs_failed"] == 1
    assert report["metrics"]["offers_inserted"] == 9
    assert report["metrics"]["offers_updated"] == 88
    assert report["metrics"]["candidates_created"] == 5
    assert report["metrics"]["safe_new_candidates_count"] == 1
    assert len(report["feeds"]) == 2
    assert "Perfumerias Comas FR" in markdown
    assert "Flaconi FR" in markdown
    assert "Feed is empty and has no CSV header." in markdown
    assert "Digest affilié hebdomadaire" in markdown
    assert report["email_report"]["attempted"] is False


def test_digest_service_renders_backlog_snapshot_when_database_is_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = build_settings(
        tmp_path,
        database_url="postgresql://digest:secret@localhost:5432/affiliate",
    )
    reports_dir = settings.reports_dir
    reports_dir.mkdir(parents=True)
    write_pipeline_report(
        reports_dir,
        "affiliate_pipeline_20260628_042520_awin.json",
        started_at="2026-06-28T04:25:20+00:00",
        finished_at="2026-06-28T04:25:32+00:00",
        status="success",
        feeds=[
            build_feed(
                advertiser_id="105475",
                advertiser_name="Perfumerias Comas FR",
                feed_id="97867",
                status="success",
                offers_inserted=3,
                offers_updated=14,
                candidates_created=2,
                safe_new_candidates_count=1,
                refresh_candidates_would_update=68,
            )
        ],
    )
    fake_cursor = FakeCursor(
        responses=[
            None,
            (1200,),
            (4800,),
            [("pending", 437), ("promoted", 12)],
            [("needs_review", 214), ("pending", 39), ("accepted_existing_perfume", 18)],
            (437,),
            (25,),
            None,
        ]
    )
    monkeypatch.setattr(
        digest_module.psycopg,
        "connect",
        lambda dsn: FakeConnection(fake_cursor),
    )

    report, _ = AffiliateDigestService(
        settings,
        now_fn=lambda: datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
    ).generate_digest(
        reports_root=reports_dir,
        since_days=7,
        locale="fr",
        output_dir=tmp_path / "out",
        email_subject=None,
        dry_run=True,
        send_email=False,
    )

    backlog = report["backlog"]
    markdown = Path(report["markdown_report_path"]).read_text(encoding="utf-8")
    assert backlog["available"] is True
    assert backlog["strict_remaining_total"] == 437
    assert backlog["needs_review_actionable_total"] == 25
    assert backlog["product_match_pending_total"] == 39
    assert backlog["accepted_existing_perfume_total"] == 18
    assert "## État backlog" in markdown
    assert "Strict restant : `437`" in markdown
    assert "`needs_review` actionnables : `25`" in markdown
    assert "`product_match_candidates.pending` : `39`" in markdown

    actionable_query, actionable_params = fake_cursor.executed[6]
    assert "%excluded_set_or_bundle%" not in actionable_query
    assert actionable_params["excluded_match_reason_pattern"] == "%excluded_set_or_bundle%"
    assert actionable_params["big_brands"] == sorted(digest_module.BIG_BRANDS)


def test_digest_service_marks_backlog_unavailable_with_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = build_settings(
        tmp_path,
        database_url="postgresql://digest:secret@localhost:5432/affiliate",
    )
    reports_dir = settings.reports_dir
    reports_dir.mkdir(parents=True)
    write_pipeline_report(
        reports_dir,
        "affiliate_pipeline_20260628_042520_awin.json",
        started_at="2026-06-28T04:25:20+00:00",
        finished_at="2026-06-28T04:25:32+00:00",
        status="success",
        feeds=[
            build_feed(
                advertiser_id="105475",
                advertiser_name="Perfumerias Comas FR",
                feed_id="97867",
                status="success",
                offers_updated=14,
            )
        ],
    )

    def failing_connect(_: str) -> FakeConnection:
        raise RuntimeError("relation public.product_match_candidates does not exist")

    monkeypatch.setattr(digest_module.psycopg, "connect", failing_connect)

    report, _ = AffiliateDigestService(
        settings,
        now_fn=lambda: datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
    ).generate_digest(
        reports_root=reports_dir,
        since_days=7,
        locale="fr",
        output_dir=tmp_path / "out",
        email_subject=None,
        dry_run=True,
        send_email=False,
    )

    markdown = Path(report["markdown_report_path"]).read_text(encoding="utf-8")
    assert report["backlog"]["available"] is False
    assert (
        report["backlog"]["warnings"][0]
        == "Backlog snapshot unavailable: relation public.product_match_candidates does not exist"
    )
    assert "Backlog indisponible" in markdown
    assert "relation public.product_match_candidates does not exist" in markdown


def test_digest_service_rejects_missing_recent_reports(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    reports_dir = settings.reports_dir
    reports_dir.mkdir(parents=True)
    write_pipeline_report(
        reports_dir,
        "affiliate_pipeline_20260601_010101_awin.json",
        started_at="2026-06-01T01:01:01+00:00",
        finished_at="2026-06-01T01:01:10+00:00",
        status="success",
        feeds=[
            build_feed(
                advertiser_id="105475",
                advertiser_name="Perfumerias Comas FR",
                feed_id="97867",
                status="success",
            )
        ],
    )

    with pytest.raises(DigestError, match="No affiliate pipeline report found"):
        AffiliateDigestService(
            settings,
            now_fn=lambda: datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        ).generate_digest(
            reports_root=reports_dir,
            since_days=7,
            locale="fr",
            output_dir=tmp_path / "out",
            email_subject=None,
            dry_run=True,
            send_email=False,
        )


def test_digest_reports_cli_outputs_paths(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AFFILIATE_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)
    write_pipeline_report(
        reports_dir,
        "affiliate_pipeline_20260628_042520_awin.json",
        started_at="2026-06-28T04:25:20+00:00",
        finished_at="2026-06-28T04:25:32+00:00",
        status="success",
        feeds=[
            build_feed(
                advertiser_id="105475",
                advertiser_name="Perfumerias Comas FR",
                feed_id="97867",
                status="success",
                offers_updated=14,
                refresh_candidates_would_update=68,
            )
        ],
    )

    exit_code = main(
        [
            "digest-reports",
            "--reports-root",
            str(reports_dir),
            "--since-days",
            "30",
            "--locale",
            "fr",
            "--output-dir",
            str(tmp_path / "digest-out"),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "markdown_report_path=" in captured.out
    assert "json_report_path=" in captured.out
    assert "email_attempted=False" in captured.out
    get_settings.cache_clear()
