from __future__ import annotations

import hashlib
import random
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from app.candidates import CandidateService
from app.config import Settings
from app.db import DatabaseService
from app.email_report import AffiliateEmailReportService
from app.matching import MatchingService
from app.normalization import NormalizationService
from app.raw_staging import RawStagingService
from app.reporting import (
    copy_report_to_latest,
    write_named_report,
)

PIPELINE_LATEST_REPORT_NAME = "latest_affiliate_pipeline_report.json"
PIPELINE_REPORT_PREFIX = "affiliate_pipeline"
LOCK_STRATEGY = "postgres_advisory_lock"


@dataclass(frozen=True)
class FeedContext:
    advertiser_db_id: int
    affiliate_feed_db_id: int
    network: str
    advertiser_id: str
    feed_id: str
    advertiser_name: str


@dataclass(frozen=True)
class PipelineRunResult:
    report: dict[str, object]
    report_path: Path
    exit_code: int


def _report_filename(network: str, started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    return f"{PIPELINE_REPORT_PREFIX}_{timestamp}_{network}.json"


def _duration_seconds(started_at: datetime, finished_at: datetime) -> float:
    return round((finished_at - started_at).total_seconds(), 3)


def _lock_keys(network: str) -> tuple[int, int]:
    digest = hashlib.sha256(f"mes-fragrances-affiliate-pipeline:{network}".encode("utf-8"))
    raw = digest.digest()
    return (
        int.from_bytes(raw[:4], byteorder="big", signed=True),
        int.from_bytes(raw[4:8], byteorder="big", signed=True),
    )


def _as_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    return int(value)


def _string_path(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)


def _step_payload(
    *,
    status: str,
    report_path: Path | None = None,
    auxiliary_paths: Mapping[str, str | Path | None] | None = None,
    error: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "report_path": _string_path(report_path),
    }
    if error:
        payload["error"] = error
    if reason:
        payload["reason"] = reason
    if auxiliary_paths:
        for key, value in auxiliary_paths.items():
            payload[key] = str(value) if value is not None else None
    return payload


def _feed_summary(
    *,
    dry_run: bool,
    raw_report: dict[str, object] | None,
    normalization_report: dict[str, object] | None,
    matching_report: dict[str, object] | None,
    candidate_report: dict[str, object] | None,
    sync_report: dict[str, object] | None,
    refresh_report: dict[str, object] | None,
    candidates_skipped: bool,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "import_run_id": (
            _as_int(matching_report.get("import_run_id"))
            if matching_report
            else (
                _as_int(raw_report.get("import_run_id"))
                if raw_report and raw_report.get("import_run_id") is not None
                else None
            )
        ),
        "rows_total": _as_int(raw_report.get("rows_total")) if raw_report else 0,
        "rows_raw_inserted": _as_int(raw_report.get("rows_inserted")) if raw_report else 0,
        "rows_duplicates": _as_int(raw_report.get("rows_duplicates")) if raw_report else 0,
        "rows_errors": _as_int(raw_report.get("rows_errors")) if raw_report else 0,
        "normalized_rows_total": (
            _as_int(normalization_report.get("raw_rows_total"))
            if normalization_report
            else 0
        ),
        "normalized_rows_inserted": (
            _as_int(normalization_report.get("normalized_rows_inserted"))
            if normalization_report
            else 0
        ),
        "rows_fragrance": (
            _as_int(normalization_report.get("rows_fragrance"))
            if normalization_report
            else 0
        ),
        "rows_excluded": (
            _as_int(normalization_report.get("rows_excluded"))
            if normalization_report
            else 0
        ),
        "rows_matched_total": (
            _as_int(matching_report.get("rows_matched_total")) if matching_report else 0
        ),
        "rows_unmatched": (
            _as_int(matching_report.get("rows_unmatched")) if matching_report else 0
        ),
        "offers_inserted": (
            _as_int(matching_report.get("offers_inserted")) if matching_report else 0
        ),
        "offers_updated": (
            _as_int(matching_report.get("offers_updated")) if matching_report else 0
        ),
        "offers_unchanged": (
            _as_int(matching_report.get("offers_unchanged")) if matching_report else 0
        ),
        "offers_price_changed": (
            _as_int(matching_report.get("offers_price_changed")) if matching_report else 0
        ),
        "stale_offers_incremented": (
            _as_int(matching_report.get("stale_offers_incremented"))
            if matching_report
            else 0
        ),
        "stale_offers_deactivated": (
            _as_int(matching_report.get("stale_offers_deactivated"))
            if matching_report
            else 0
        ),
        "candidates_created": 0 if candidates_skipped else 0,
        "candidates_updated": (
            _as_int(candidate_report.get("candidates_updated"))
            if candidate_report
            else 0
        ),
        "candidates_unchanged": (
            _as_int(candidate_report.get("candidates_unchanged"))
            if candidate_report
            else 0
        ),
        "staging_inserted": (
            _as_int(sync_report.get("staging_inserted")) if sync_report else 0
        ),
        "staging_updated": (
            _as_int(sync_report.get("staging_updated")) if sync_report else 0
        ),
        "staging_ignored_manual_status": (
            _as_int(sync_report.get("staging_ignored_manual_status"))
            if sync_report
            else 0
        ),
        "safe_new_candidates_count": (
            _as_int(sync_report.get("safe_new_candidates_count")) if sync_report else 0
        ),
        "sync_safe_top_brands": (
            list(sync_report.get("safe_top_brands") or []) if sync_report else []
        ),
        "refresh_candidates_loaded": (
            _as_int(refresh_report.get("candidates_loaded")) if refresh_report else 0
        ),
        "refresh_candidates_would_update": (
            _as_int(refresh_report.get("candidates_updated")) if refresh_report else 0
        ),
        "refresh_candidates_without_match": (
            _as_int(refresh_report.get("candidates_without_match"))
            if refresh_report
            else 0
        ),
        "refresh_candidates_unchanged": (
            _as_int(refresh_report.get("candidates_unchanged")) if refresh_report else 0
        ),
        "refresh_candidates_ignored_closed_status": (
            _as_int(refresh_report.get("candidates_ignored_closed_status"))
            if refresh_report
            else 0
        ),
    }
    if candidate_report is not None and not dry_run:
        summary["candidates_created"] = _as_int(candidate_report.get("candidates_created"))
    if candidate_report is not None and dry_run:
        summary["estimated_candidates_created"] = _as_int(
            candidate_report.get("candidates_created")
        )
    return summary


class PipelineService:
    def __init__(
        self,
        settings: Settings,
        *,
        db_service: DatabaseService | None = None,
        raw_staging_service: RawStagingService | None = None,
        normalization_service: NormalizationService | None = None,
        matching_service: MatchingService | None = None,
        candidate_service: CandidateService | None = None,
        email_report_service: AffiliateEmailReportService | None = None,
        sleep_func: Callable[[float], None] | None = None,
        randint_func: Callable[[int, int], int] | None = None,
    ) -> None:
        self.settings = settings
        self.db_service = db_service or DatabaseService(settings)
        self.raw_staging_service = raw_staging_service or RawStagingService(settings)
        self.normalization_service = normalization_service or NormalizationService(settings)
        self.matching_service = matching_service or MatchingService(settings)
        self.candidate_service = candidate_service or CandidateService(settings)
        self.email_report_service = email_report_service or AffiliateEmailReportService(
            settings
        )
        self.sleep_func = sleep_func or time.sleep
        self.randint_func = randint_func or random.randint

    def run_pipeline(
        self,
        *,
        network: str,
        dry_run: bool,
        advertiser_id: str | None = None,
        feed_id: str | None = None,
        random_delay_max_seconds: int = 0,
        skip_candidates: bool = False,
        skip_candidate_sync: bool = False,
        skip_refresh_dry_run: bool = False,
        no_stale_update: bool = False,
        email_report: bool | None = None,
    ) -> PipelineRunResult:
        started_at = datetime.now(timezone.utc)
        report: dict[str, object] = {
            "status": "error",
            "command": "run-affiliate-pipeline",
            "network": network,
            "dry_run": dry_run,
            "started_at": started_at.isoformat(),
            "finished_at": None,
            "duration_seconds": 0,
            "lock_strategy": LOCK_STRATEGY,
            "lock_acquired": False,
            "random_delay_seconds": 0,
            "feeds_total": 0,
            "feeds_succeeded": 0,
            "feeds_failed": 0,
            "feeds_skipped": 0,
            "filters": {
                "advertiser_id": advertiser_id,
                "feed_id": feed_id,
                "skip_candidates": skip_candidates,
                "skip_candidate_sync": skip_candidate_sync,
                "skip_refresh_dry_run": skip_refresh_dry_run,
                "no_stale_update": no_stale_update,
                "email_report": email_report,
            },
            "totals": {
                "rows_matched_total": 0,
                "rows_unmatched": 0,
                "raw_rows_total": 0,
                "raw_rows_inserted": 0,
                "raw_rows_duplicates": 0,
                "normalized_rows_total": 0,
                "normalized_rows_inserted": 0,
                "offers_inserted": 0,
                "offers_updated": 0,
                "offers_unchanged": 0,
                "offers_price_changed": 0,
                "stale_offers_incremented": 0,
                "stale_offers_deactivated": 0,
                "candidates_created": 0,
                "candidates_updated": 0,
                "candidates_unchanged": 0,
                "staging_inserted": 0,
                "staging_updated": 0,
                "staging_ignored_manual_status": 0,
                "safe_new_candidates_count": 0,
                "refresh_candidates_loaded": 0,
                "refresh_candidates_would_update": 0,
                "refresh_candidates_without_match": 0,
                "refresh_candidates_unchanged": 0,
                "refresh_candidates_ignored_closed_status": 0,
                "rows_errors": 0,
            },
            "latest_import_run_id": None,
            "perfume_insert_candidates_counts": {},
            "safe_top_brands": [],
            "email_report": {},
            "feeds": [],
            "warnings": [],
        }

        lock_conn: Any | None = None
        lock_acquired = False
        try:
            self.db_service.require_database_url()
            if random_delay_max_seconds < 0:
                raise ValueError("--random-delay-max-seconds must be >= 0")

            if random_delay_max_seconds > 0:
                delay_seconds = self.randint_func(0, random_delay_max_seconds)
                report["random_delay_seconds"] = delay_seconds
                if delay_seconds > 0:
                    self.sleep_func(delay_seconds)

            lock_conn = self.db_service.connect(autocommit=True)
            lock_acquired = self._try_acquire_pipeline_lock(lock_conn, network=network)
            report["lock_acquired"] = lock_acquired
            if not lock_acquired:
                report["status"] = "skipped_locked"
                report["warnings"].append(
                    "Another affiliate pipeline run is already active; skipping."
                )
                return self._finalize_result(report, started_at, exit_code=2)

            with self.db_service.connect() as conn:
                feeds = self._load_active_feeds(
                    conn,
                    network=network,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )

            report["feeds_total"] = len(feeds)
            if not feeds:
                report["status"] = "success"
                report["warnings"].append("No active affiliate feeds matched the selection.")
                return self._finalize_result(report, started_at, exit_code=0)

            for feed in feeds:
                feed_result = self._process_feed(
                    feed,
                    dry_run=dry_run,
                    skip_candidates=skip_candidates,
                    skip_candidate_sync=skip_candidate_sync,
                    skip_refresh_dry_run=skip_refresh_dry_run,
                    no_stale_update=no_stale_update,
                    started_at=started_at,
                )
                report["feeds"].append(feed_result)
                if feed_result["status"] == "success":
                    report["feeds_succeeded"] = _as_int(report["feeds_succeeded"]) + 1
                elif feed_result["status"] == "skipped":
                    report["feeds_skipped"] = _as_int(report["feeds_skipped"]) + 1
                else:
                    report["feeds_failed"] = _as_int(report["feeds_failed"]) + 1

                self._accumulate_totals(report["totals"], feed_result["summary"], dry_run=dry_run)
                import_run_id = dict(feed_result.get("summary", {})).get("import_run_id")
                if import_run_id:
                    report["latest_import_run_id"] = import_run_id

            report["safe_top_brands"] = self._aggregate_safe_top_brands(report["feeds"])
            report["perfume_insert_candidates_counts"] = (
                self._load_perfume_insert_candidate_counts(report)
            )

            report["status"] = (
                "failed" if _as_int(report["feeds_failed"]) > 0 else "success"
            )
            exit_code = 1 if report["status"] == "failed" else 0
            return self._finalize_result(
                report,
                started_at,
                exit_code=exit_code,
                email_report=email_report,
            )
        except Exception as exc:
            report["status"] = "failed"
            report["error"] = str(exc)
            report["warnings"].append("Pipeline aborted before all feeds completed.")
            return self._finalize_result(
                report,
                started_at,
                exit_code=1,
                email_report=email_report,
            )
        finally:
            if lock_conn is not None:
                try:
                    if lock_acquired:
                        self._release_pipeline_lock(lock_conn, network=network)
                finally:
                    lock_conn.close()

    def _load_active_feeds(
        self,
        conn: Any,
        *,
        network: str,
        advertiser_id: str | None,
        feed_id: str | None,
    ) -> list[FeedContext]:
        sql = """
            select
                a.id as advertiser_db_id,
                af.id as affiliate_feed_db_id,
                a.network_advertiser_id as advertiser_id,
                af.network_feed_id as feed_id,
                a.name as advertiser_name,
                af.network
            from advertisers a
            join affiliate_feeds af
              on af.advertiser_id = a.id
            where a.network = %s
              and af.network = %s
              and a.active = true
              and af.active = true
        """
        params: list[object] = [network, network]
        if advertiser_id is not None:
            sql += " and a.network_advertiser_id = %s"
            params.append(advertiser_id)
        if feed_id is not None:
            sql += " and af.network_feed_id = %s"
            params.append(feed_id)
        sql += " order by a.priority asc, a.id asc, af.id asc"

        rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            FeedContext(
                advertiser_db_id=int(row["advertiser_db_id"]),
                affiliate_feed_db_id=int(row["affiliate_feed_db_id"]),
                network=str(row["network"]),
                advertiser_id=str(row["advertiser_id"]),
                feed_id=str(row["feed_id"]),
                advertiser_name=str(row["advertiser_name"]),
            )
            for row in rows
        ]

    def _process_feed(
        self,
        feed: FeedContext,
        *,
        dry_run: bool,
        skip_candidates: bool,
        skip_candidate_sync: bool,
        skip_refresh_dry_run: bool,
        no_stale_update: bool,
        started_at: datetime,
    ) -> dict[str, object]:
        raw_report: dict[str, object] | None = None
        normalization_report: dict[str, object] | None = None
        matching_report: dict[str, object] | None = None
        candidate_report: dict[str, object] | None = None
        sync_report: dict[str, object] | None = None
        refresh_report: dict[str, object] | None = None

        feed_result: dict[str, object] = {
            "network": feed.network,
            "advertiser_id": feed.advertiser_id,
            "feed_id": feed.feed_id,
            "advertiser_name": feed.advertiser_name,
            "advertiser_db_id": feed.advertiser_db_id,
            "affiliate_feed_db_id": feed.affiliate_feed_db_id,
            "status": "success",
            "steps": {},
            "summary": {},
            "warnings": [],
        }

        try:
            raw_report, raw_path = self.raw_staging_service.import_remote_feed(
                network=feed.network,
                advertiser_id=feed.advertiser_id,
                feed_id=feed.feed_id,
                dry_run=dry_run,
            )
            feed_result["steps"]["raw_import"] = _step_payload(
                status="success",
                report_path=raw_path,
            )
        except Exception as exc:
            feed_result["status"] = "failed"
            feed_result["steps"]["raw_import"] = _step_payload(status="failed", error=str(exc))
            feed_result["steps"]["normalization"] = _step_payload(
                status="skipped",
                reason="raw_import_failed",
            )
            feed_result["steps"]["matching"] = _step_payload(
                status="skipped",
                reason="raw_import_failed",
            )
            feed_result["steps"]["candidates"] = _step_payload(
                status="skipped",
                reason="raw_import_failed",
            )
            feed_result["steps"]["candidate_sync"] = _step_payload(
                status="skipped",
                reason="raw_import_failed",
            )
            feed_result["steps"]["refresh_dry_run"] = _step_payload(
                status="skipped",
                reason="raw_import_failed",
            )
            feed_result["warnings"].append(str(exc))
            feed_result["summary"] = _feed_summary(
                dry_run=dry_run,
                raw_report=raw_report,
                normalization_report=None,
                matching_report=None,
                candidate_report=None,
                sync_report=None,
                refresh_report=None,
                candidates_skipped=skip_candidates,
            )
            return feed_result

        try:
            normalization_report, normalization_path = self.normalization_service.normalize_feed(
                advertiser_id=feed.advertiser_id,
                feed_id=feed.feed_id,
                dry_run=dry_run,
            )
            feed_result["steps"]["normalization"] = _step_payload(
                status="success",
                report_path=normalization_path,
            )
        except Exception as exc:
            feed_result["status"] = "failed"
            feed_result["steps"]["normalization"] = _step_payload(
                status="failed",
                error=str(exc),
            )
            feed_result["steps"]["matching"] = _step_payload(
                status="skipped",
                reason="normalization_failed",
            )
            feed_result["steps"]["candidates"] = _step_payload(
                status="skipped",
                reason="normalization_failed",
            )
            feed_result["steps"]["candidate_sync"] = _step_payload(
                status="skipped",
                reason="normalization_failed",
            )
            feed_result["steps"]["refresh_dry_run"] = _step_payload(
                status="skipped",
                reason="normalization_failed",
            )
            feed_result["warnings"].append(str(exc))
            feed_result["summary"] = _feed_summary(
                dry_run=dry_run,
                raw_report=raw_report,
                normalization_report=normalization_report,
                matching_report=None,
                candidate_report=None,
                sync_report=None,
                refresh_report=None,
                candidates_skipped=skip_candidates,
            )
            return feed_result

        try:
            safe_stale_update = self._safe_to_update_stale(raw_report)
            matching_report, matching_path = self.matching_service.match_offers(
                advertiser_id=feed.advertiser_id,
                feed_id=feed.feed_id,
                dry_run=dry_run,
                no_stale_update=dry_run or no_stale_update or not safe_stale_update,
            )
            feed_result["steps"]["matching"] = _step_payload(
                status="success",
                report_path=matching_path,
            )
            if not safe_stale_update and not dry_run and not no_stale_update:
                feed_result["warnings"].append(
                    "Stale offer update skipped because the current raw import did not "
                    "materialize a full snapshot for this feed."
                )
        except Exception as exc:
            feed_result["status"] = "failed"
            feed_result["steps"]["matching"] = _step_payload(status="failed", error=str(exc))
            feed_result["steps"]["candidates"] = _step_payload(
                status="skipped",
                reason="matching_failed",
            )
            feed_result["steps"]["candidate_sync"] = _step_payload(
                status="skipped",
                reason="matching_failed",
            )
            feed_result["steps"]["refresh_dry_run"] = _step_payload(
                status="skipped",
                reason="matching_failed",
            )
            feed_result["warnings"].append(str(exc))
            feed_result["summary"] = _feed_summary(
                dry_run=dry_run,
                raw_report=raw_report,
                normalization_report=normalization_report,
                matching_report=matching_report,
                candidate_report=None,
                sync_report=None,
                refresh_report=None,
                candidates_skipped=skip_candidates,
            )
            return feed_result

        if skip_candidates:
            feed_result["steps"]["candidates"] = _step_payload(
                status="skipped",
                reason="disabled_by_cli",
            )
            feed_result["steps"]["candidate_sync"] = _step_payload(
                status="skipped",
                reason="candidates_disabled_by_cli",
            )
            feed_result["steps"]["refresh_dry_run"] = _step_payload(
                status="skipped",
                reason="candidates_disabled_by_cli",
            )
            feed_result["warnings"].append("Candidate generation disabled by CLI flag.")
            feed_result["summary"] = _feed_summary(
                dry_run=dry_run,
                raw_report=raw_report,
                normalization_report=normalization_report,
                matching_report=matching_report,
                candidate_report=None,
                sync_report=None,
                refresh_report=None,
                candidates_skipped=True,
            )
            return feed_result

        try:
            candidate_report, candidate_path = self.candidate_service.create_candidates(
                advertiser_id=feed.advertiser_id,
                feed_id=feed.feed_id,
                dry_run=dry_run,
            )
            feed_result["steps"]["candidates"] = _step_payload(
                status="success",
                report_path=candidate_path,
            )
        except Exception as exc:
            feed_result["status"] = "failed"
            feed_result["steps"]["candidates"] = _step_payload(status="failed", error=str(exc))
            feed_result["steps"]["candidate_sync"] = _step_payload(
                status="skipped",
                reason="candidates_failed",
            )
            feed_result["steps"]["refresh_dry_run"] = _step_payload(
                status="skipped",
                reason="candidates_failed",
            )
            feed_result["warnings"].append(str(exc))
            feed_result["summary"] = _feed_summary(
                dry_run=dry_run,
                raw_report=raw_report,
                normalization_report=normalization_report,
                matching_report=matching_report,
                candidate_report=None,
                sync_report=None,
                refresh_report=None,
                candidates_skipped=False,
            )
            return feed_result

        report_dir = self._feed_report_dir(started_at=started_at, feed=feed)

        if skip_candidate_sync:
            feed_result["steps"]["candidate_sync"] = _step_payload(
                status="skipped",
                reason="disabled_by_cli",
            )
            feed_result["warnings"].append("Perfume insert candidate sync disabled by CLI flag.")
        else:
            try:
                sync_report, sync_path = self.candidate_service.sync_perfume_insert_candidates(
                    advertiser_id=feed.advertiser_id,
                    feed_id=feed.feed_id,
                    dry_run=dry_run,
                    report_dir=report_dir,
                    only_statuses=["pending", "needs_review"],
                )
                feed_result["steps"]["candidate_sync"] = _step_payload(
                    status="success",
                    report_path=sync_path,
                    auxiliary_paths={
                        "markdown_report_path": sync_report.get("markdown_report_path"),
                        "safe_csv_path": sync_report.get("safe_csv_path"),
                    },
                )
            except Exception as exc:
                feed_result["status"] = "failed"
                feed_result["steps"]["candidate_sync"] = _step_payload(
                    status="failed",
                    error=str(exc),
                )
                feed_result["steps"]["refresh_dry_run"] = _step_payload(
                    status="skipped",
                    reason="candidate_sync_failed",
                )
                feed_result["warnings"].append(str(exc))
                feed_result["summary"] = _feed_summary(
                    dry_run=dry_run,
                    raw_report=raw_report,
                    normalization_report=normalization_report,
                    matching_report=matching_report,
                    candidate_report=candidate_report,
                    sync_report=None,
                    refresh_report=None,
                    candidates_skipped=False,
                )
                return feed_result

        if skip_refresh_dry_run:
            feed_result["steps"]["refresh_dry_run"] = _step_payload(
                status="skipped",
                reason="disabled_by_cli",
            )
            feed_result["warnings"].append(
                "Historical candidate refresh dry-run disabled by CLI flag."
            )
        else:
            try:
                refresh_report, refresh_path = (
                    self.candidate_service.refresh_product_match_candidates(
                        advertiser_id=feed.advertiser_id,
                        feed_id=feed.feed_id,
                        dry_run=True,
                        report_dir=report_dir,
                        only_statuses=["pending", "needs_review"],
                    )
                )
                feed_result["steps"]["refresh_dry_run"] = _step_payload(
                    status="success",
                    report_path=refresh_path,
                    auxiliary_paths={
                        "markdown_report_path": refresh_report.get(
                            "markdown_report_path"
                        ),
                        "csv_report_path": refresh_report.get("csv_report_path"),
                    },
                )
            except Exception as exc:
                feed_result["steps"]["refresh_dry_run"] = _step_payload(
                    status="failed",
                    error=str(exc),
                )
                feed_result["warnings"].append(
                    f"Historical candidate refresh dry-run failed: {exc}"
                )

        feed_result["summary"] = _feed_summary(
            dry_run=dry_run,
            raw_report=raw_report,
            normalization_report=normalization_report,
            matching_report=matching_report,
            candidate_report=candidate_report,
            sync_report=sync_report,
            refresh_report=refresh_report,
            candidates_skipped=False,
        )
        return feed_result

    def _feed_report_dir(self, *, started_at: datetime, feed: FeedContext) -> Path:
        stamp = started_at.strftime("%Y%m%d_%H%M%S")
        report_dir = (
            self.settings.reports_dir
            / f"affiliate_pipeline_steps_{stamp}_{feed.network}"
            / f"{feed.advertiser_id}_{feed.feed_id}"
        )
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir

    def _load_perfume_insert_candidate_counts(
        self,
        report: dict[str, object],
    ) -> dict[str, int]:
        try:
            with self.db_service.connect() as conn:
                rows = conn.execute(
                    """
                    select review_status, count(*) as count
                    from public.perfume_insert_candidates
                    group by review_status
                    """
                ).fetchall()
        except Exception as exc:
            report["warnings"].append(
                "Could not load perfume_insert_candidates counts: "
                f"{exc}"
            )
            return {}
        return {str(row["review_status"]): int(row["count"]) for row in rows}

    def _aggregate_safe_top_brands(
        self,
        feeds: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        counts: Counter[str] = Counter()
        for feed in feeds:
            summary = dict(feed.get("summary", {}))
            for row in summary.get("sync_safe_top_brands", []):
                if not isinstance(row, dict):
                    continue
                counts[str(row.get("candidate_brand", "<missing>"))] += _as_int(
                    row.get("count")
                )
        return [
            {"candidate_brand": brand, "count": count}
            for brand, count in counts.most_common(10)
        ]

    def _try_acquire_pipeline_lock(self, conn: Any, *, network: str) -> bool:
        key_one, key_two = _lock_keys(network)
        row = conn.execute(
            "select pg_try_advisory_lock(%s, %s) as acquired",
            (key_one, key_two),
        ).fetchone()
        return bool(row["acquired"]) if row is not None else False

    def _release_pipeline_lock(self, conn: Any, *, network: str) -> None:
        key_one, key_two = _lock_keys(network)
        conn.execute(
            "select pg_advisory_unlock(%s, %s)",
            (key_one, key_two),
        ).fetchone()

    def _accumulate_totals(
        self,
        totals: dict[str, object],
        summary: dict[str, object],
        *,
        dry_run: bool,
    ) -> None:
        totals["raw_rows_total"] = _as_int(totals["raw_rows_total"]) + _as_int(
            summary.get("rows_total")
        )
        totals["raw_rows_inserted"] = _as_int(totals["raw_rows_inserted"]) + _as_int(
            summary.get("rows_raw_inserted")
        )
        totals["raw_rows_duplicates"] = _as_int(totals["raw_rows_duplicates"]) + _as_int(
            summary.get("rows_duplicates")
        )
        totals["normalized_rows_total"] = _as_int(
            totals["normalized_rows_total"]
        ) + _as_int(summary.get("normalized_rows_total"))
        totals["normalized_rows_inserted"] = _as_int(
            totals["normalized_rows_inserted"]
        ) + (0 if dry_run else _as_int(summary.get("normalized_rows_inserted")))
        totals["rows_matched_total"] = _as_int(totals["rows_matched_total"]) + _as_int(
            summary.get("rows_matched_total")
        )
        totals["rows_unmatched"] = _as_int(totals["rows_unmatched"]) + _as_int(
            summary.get("rows_unmatched")
        )
        totals["offers_inserted"] = _as_int(totals["offers_inserted"]) + _as_int(
            summary.get("offers_inserted")
        )
        totals["offers_updated"] = _as_int(totals["offers_updated"]) + _as_int(
            summary.get("offers_updated")
        )
        totals["offers_unchanged"] = _as_int(totals["offers_unchanged"]) + _as_int(
            summary.get("offers_unchanged")
        )
        totals["offers_price_changed"] = _as_int(
            totals["offers_price_changed"]
        ) + _as_int(summary.get("offers_price_changed"))
        totals["stale_offers_incremented"] = _as_int(
            totals["stale_offers_incremented"]
        ) + (0 if dry_run else _as_int(summary.get("stale_offers_incremented")))
        totals["stale_offers_deactivated"] = _as_int(
            totals["stale_offers_deactivated"]
        ) + (0 if dry_run else _as_int(summary.get("stale_offers_deactivated")))
        totals["candidates_created"] = _as_int(totals["candidates_created"]) + _as_int(
            summary.get("candidates_created")
        )
        totals["candidates_updated"] = _as_int(totals["candidates_updated"]) + _as_int(
            summary.get("candidates_updated")
        )
        totals["candidates_unchanged"] = _as_int(
            totals["candidates_unchanged"]
        ) + _as_int(summary.get("candidates_unchanged"))
        totals["staging_inserted"] = _as_int(totals["staging_inserted"]) + _as_int(
            summary.get("staging_inserted")
        )
        totals["staging_updated"] = _as_int(totals["staging_updated"]) + _as_int(
            summary.get("staging_updated")
        )
        totals["staging_ignored_manual_status"] = _as_int(
            totals["staging_ignored_manual_status"]
        ) + _as_int(summary.get("staging_ignored_manual_status"))
        totals["safe_new_candidates_count"] = _as_int(
            totals["safe_new_candidates_count"]
        ) + _as_int(summary.get("safe_new_candidates_count"))
        totals["refresh_candidates_loaded"] = _as_int(
            totals["refresh_candidates_loaded"]
        ) + _as_int(summary.get("refresh_candidates_loaded"))
        totals["refresh_candidates_would_update"] = _as_int(
            totals["refresh_candidates_would_update"]
        ) + _as_int(summary.get("refresh_candidates_would_update"))
        totals["refresh_candidates_without_match"] = _as_int(
            totals["refresh_candidates_without_match"]
        ) + _as_int(summary.get("refresh_candidates_without_match"))
        totals["refresh_candidates_unchanged"] = _as_int(
            totals["refresh_candidates_unchanged"]
        ) + _as_int(summary.get("refresh_candidates_unchanged"))
        totals["refresh_candidates_ignored_closed_status"] = _as_int(
            totals["refresh_candidates_ignored_closed_status"]
        ) + _as_int(summary.get("refresh_candidates_ignored_closed_status"))
        totals["rows_errors"] = _as_int(totals["rows_errors"]) + _as_int(
            summary.get("rows_errors")
        )

    def _safe_to_update_stale(self, raw_report: dict[str, object] | None) -> bool:
        if raw_report is None:
            return False
        rows_total = _as_int(raw_report.get("rows_total"))
        rows_inserted = _as_int(raw_report.get("rows_inserted"))
        rows_duplicates = _as_int(raw_report.get("rows_duplicates"))
        return rows_total > 0 and rows_inserted == rows_total and rows_duplicates == 0

    def _finalize_result(
        self,
        report: dict[str, object],
        started_at: datetime,
        *,
        exit_code: int,
        email_report: bool | None,
    ) -> PipelineRunResult:
        finished_at = datetime.now(timezone.utc)
        report["finished_at"] = finished_at.isoformat()
        report["duration_seconds"] = _duration_seconds(started_at, finished_at)
        report_path = self._write_pipeline_report(report, started_at)
        email_result = self.email_report_service.send_pipeline_report(
            report,
            report_path,
            force_enabled=email_report,
        )
        report["email_report"] = email_result
        if email_result.get("attempted") and not email_result.get("success"):
            report.setdefault("warnings", []).append(
                f"Affiliate email report failed: {email_result.get('error', 'unknown error')}"
            )
        report_path = self._write_pipeline_report(report, started_at)
        return PipelineRunResult(report=report, report_path=report_path, exit_code=exit_code)

    def _write_pipeline_report(self, report: dict[str, object], started_at: datetime) -> Path:
        filename = _report_filename(str(report["network"]), started_at)
        report_path = write_named_report(self.settings.affiliate_data_dir, filename, report)
        copy_report_to_latest(
            report_path,
            self.settings.reports_dir / PIPELINE_LATEST_REPORT_NAME,
        )
        return report_path


def format_pipeline_report_summary(report: dict[str, object], report_path: Path) -> str:
    lines = [
        f"status={report.get('status')}",
        f"dry_run={report.get('dry_run')}",
        f"network={report.get('network')}",
        f"feeds_total={report.get('feeds_total')}",
        f"feeds_succeeded={report.get('feeds_succeeded')}",
        f"feeds_failed={report.get('feeds_failed')}",
        f"offers_inserted={dict(report.get('totals', {})).get('offers_inserted', 0)}",
        f"offers_updated={dict(report.get('totals', {})).get('offers_updated', 0)}",
        f"candidates_created={dict(report.get('totals', {})).get('candidates_created', 0)}",
        (
            "staging_inserted="
            f"{dict(report.get('totals', {})).get('staging_inserted', 0)}"
        ),
        (
            "refresh_candidates_would_update="
            f"{dict(report.get('totals', {})).get('refresh_candidates_would_update', 0)}"
        ),
        f"lock_acquired={report.get('lock_acquired')}",
        f"report_path={report_path}",
    ]
    if report.get("error"):
        lines.append(f"error={report.get('error')}")
    email_report = dict(report.get("email_report", {}))
    if email_report:
        lines.append(f"email_attempted={email_report.get('attempted')}")
        lines.append(f"email_success={email_report.get('success')}")
    return "\n".join(lines)
