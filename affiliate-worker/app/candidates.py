from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from app.config import Settings
from app.db import DatabaseService
from app.matching import (
    CatalogPerfume,
    LoadedNormalizedItem,
    MatchingService,
    MatchResult,
    build_perfume_match_key,
)
from app.normalization import normalize_text
from app.reporting import try_write_report, write_report

MANUAL_FINAL_CANDIDATE_STATUSES = {
    "accepted_existing_perfume",
    "accepted_new_variant",
    "accepted_new_perfume",
    "rejected_not_perfume",
    "rejected_duplicate",
    "ignored",
}
AUTO_MUTABLE_CANDIDATE_STATUSES = {"pending", "needs_review"}
COMMERCIAL_EXCLUDED_REASONS = {"set_or_bundle", "refill"}
REJECTED_EXCLUDED_REASONS = {"body_product", "home_fragrance"}
IGNORED_EXCLUDED_REASONS = {"tester"}
STAGING_MUTABLE_REVIEW_STATUSES = {"pending"}
STAGING_FINAL_REVIEW_STATUSES = {
    "approved",
    "promoted",
    "rejected",
    "merged_existing",
    "needs_more_info",
}
SAFE_INSERT_CANDIDATE = "SAFE_INSERT_CANDIDATE"
NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
VARIANT_OF_EXISTING = "VARIANT_OF_EXISTING"
NON_PERFUME_PRODUCT = "NON_PERFUME_PRODUCT"
NON_PERFUME_PATTERNS = (
    "coffret",
    "set",
    "discovery",
    "sample",
    "tester",
    "refill",
    "recharge",
    "bougie",
    "candle",
    "body",
    "lotion",
    "gel douche",
    "shower gel",
    "savon",
    "soap",
    "after shave",
    "diffuseur",
    "home parfum",
    "home fragrance",
)


class CandidateError(RuntimeError):
    """Raised when candidate generation cannot complete safely."""


@dataclass(frozen=True)
class CandidateDecision:
    item: LoadedNormalizedItem
    dedupe_key: str
    status: str
    proposed_perfume_id: str | None
    match_score: Decimal | None
    match_reason: str
    source_classification: str
    match_status_from_pr07: str
    match_method: str
    match_components: dict[str, object]


@dataclass(frozen=True)
class CandidateAggregate:
    dedupe_key: str
    primary: CandidateDecision
    source_count: int


@dataclass(frozen=True)
class InsertCandidateClassification:
    source_candidate_id: int
    source_offer_id: int | None
    candidate_brand: str | None
    candidate_name: str
    candidate_concentration: str | None
    candidate_volume_ml: Decimal | None
    candidate_category: str | None
    candidate_ean: str | None
    candidate_gtin: str | None
    candidate_upc: str | None
    candidate_mpn: str | None
    candidate_image_url: str | None
    candidate_source_title: str | None
    candidate_affiliate_url: str | None
    classification: str
    confidence: Decimal | None
    duplicate_risk: str | None
    duplicate_reason: str | None
    nearest_perfume_id: str | None
    nearest_perfume_brand: str | None
    nearest_perfume_name: str | None
    source_status: str

    def as_csv_row(self) -> dict[str, object]:
        return {
            "source_candidate_id": self.source_candidate_id,
            "candidate_brand": self.candidate_brand or "",
            "candidate_name": self.candidate_name,
            "candidate_concentration": self.candidate_concentration or "",
            "candidate_volume_ml": _decimal_to_string(self.candidate_volume_ml) or "",
            "candidate_ean": self.candidate_ean or "",
            "candidate_gtin": self.candidate_gtin or "",
            "candidate_upc": self.candidate_upc or "",
            "candidate_mpn": self.candidate_mpn or "",
            "candidate_image_url": self.candidate_image_url or "",
            "candidate_source_title": self.candidate_source_title or "",
            "classification": self.classification,
            "confidence": _decimal_to_string(self.confidence) or "",
            "duplicate_risk": self.duplicate_risk or "",
            "duplicate_reason": self.duplicate_reason or "",
            "nearest_perfume_id": self.nearest_perfume_id or "",
            "nearest_perfume_brand": self.nearest_perfume_brand or "",
            "nearest_perfume_name": self.nearest_perfume_name or "",
            "source_status": self.source_status,
        }


@dataclass(frozen=True)
class CandidateRefreshEvaluation:
    candidate_id: int
    candidate_brand: str | None
    candidate_name: str
    status_before: str
    status_after: str
    proposed_perfume_id_before: str | None
    proposed_perfume_id_after: str | None
    match_score_before: Decimal | None
    match_score_after: Decimal | None
    match_reason_before: str | None
    match_reason_after: str | None
    source_import_run_id: int | None
    source_network_product_id: str | None
    source_merchant_product_id: str | None
    action: str

    def as_csv_row(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_brand": self.candidate_brand or "",
            "candidate_name": self.candidate_name,
            "status_before": self.status_before,
            "status_after": self.status_after,
            "proposed_perfume_id_before": self.proposed_perfume_id_before or "",
            "proposed_perfume_id_after": self.proposed_perfume_id_after or "",
            "match_score_before": _decimal_to_string(self.match_score_before) or "",
            "match_score_after": _decimal_to_string(self.match_score_after) or "",
            "match_reason_before": self.match_reason_before or "",
            "match_reason_after": self.match_reason_after or "",
            "source_import_run_id": self.source_import_run_id or "",
            "source_network_product_id": self.source_network_product_id or "",
            "source_merchant_product_id": self.source_merchant_product_id or "",
            "action": self.action,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _report_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_text_blob(*parts: str | None) -> str:
    return " ".join(normalize_text(part) for part in parts if normalize_text(part)).strip()


def _identifier_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal_from_value(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _int_from_value(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def build_candidate_dedupe_key(item: LoadedNormalizedItem) -> str:
    normalized_brand = item.normalized_brand or ""
    normalized_name = build_perfume_match_key(
        item.title,
        brand=item.brand,
        concentration=item.concentration,
        volume_ml=item.volume_ml,
    ) or item.normalized_title
    volume_text = _decimal_to_string(item.volume_ml) or ""
    stable_external_id = item.network_product_id or item.merchant_product_id or item.raw_hash
    return "|".join(
        [
            "v1",
            str(item.advertiser_id),
            stable_external_id,
            normalized_brand,
            normalized_name,
            item.concentration or "",
            volume_text,
        ]
    )


class CandidateService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_service = DatabaseService(settings)
        self.matching_service = MatchingService(settings)

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
        self.db_service.require_database_url()

        auto_threshold = int(self.settings.affiliate_match_auto_threshold)
        review_threshold = int(
            min_review_score or self.settings.affiliate_match_review_threshold
        )
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "create-candidates",
            "network": "awin",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "dry_run": dry_run,
            "source": "normalized_feed_items",
            "database_url_redacted": True,
            "selection_limit": limit,
            "include_excluded": include_excluded,
            "disable_fuzzy": disable_fuzzy,
            "auto_threshold": auto_threshold,
            "review_threshold": review_threshold,
            "candidate_status_counts": {},
            "sample_candidates_created": [],
            "sample_candidates_updated": [],
            "sample_ignored_existing_status": [],
            "warnings": [],
        }

        try:
            with self.db_service.connect() as conn:
                self._ensure_candidate_dedupe_column(conn)
                advertiser_row, affiliate_feed_row = self.matching_service._resolve_feed_context(  # noqa: SLF001
                    conn,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )
                import_run_id = self.matching_service._select_source_import_run(  # noqa: SLF001
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                )
                normalized_items = self.matching_service._load_normalized_rows(  # noqa: SLF001
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                    import_run_id=import_run_id,
                    limit=limit,
                )
                if not normalized_items:
                    raise CandidateError(
                        "No normalized_feed_items found for the latest successful import run."
                    )

                (
                    catalog_rows,
                    available_catalog_columns,
                ) = self.matching_service._load_catalog_perfumes(conn)  # noqa: SLF001
                locked_mappings = self.matching_service._load_locked_mappings(  # noqa: SLF001
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    auto_threshold=auto_threshold,
                )
                catalog_identifier_fields = [
                    field
                    for field in ("ean", "gtin", "upc", "mpn")
                    if field in available_catalog_columns
                ]
                catalog_by_brand: dict[str, list[object]] = {}
                for perfume in catalog_rows:
                    catalog_by_brand.setdefault(perfume.normalized_brand, []).append(perfume)

                rows_excluded_total = sum(1 for item in normalized_items if item.is_excluded)
                rows_actionable_input = 0
                rows_confident_matched_existing_offer = 0
                rows_needs_review_from_matching = 0
                rows_unmatched_from_matching = 0
                rows_excluded_considered = 0
                candidate_decisions: list[CandidateDecision] = []

                for item in normalized_items:
                    if item.is_excluded:
                        decision = self._build_excluded_decision(
                            conn,
                            item=item,
                            advertiser_db_id=int(advertiser_row["id"]),
                            catalog_rows=catalog_rows,
                            catalog_by_brand=catalog_by_brand,
                            catalog_identifier_fields=catalog_identifier_fields,
                            locked_mappings=locked_mappings,
                            auto_threshold=auto_threshold,
                            review_threshold=review_threshold,
                            disable_fuzzy=disable_fuzzy,
                            include_excluded=include_excluded,
                        )
                        if decision is not None:
                            rows_excluded_considered += 1
                            candidate_decisions.append(decision)
                        continue

                    if not item.is_fragrance:
                        continue

                    missing_required = self.matching_service._missing_required_fields(item)  # noqa: SLF001
                    if missing_required:
                        continue

                    rows_actionable_input += 1
                    match_result = self.matching_service._match_item(  # noqa: SLF001
                        item,
                        catalog_rows=catalog_rows,
                        catalog_by_brand=catalog_by_brand,
                        catalog_identifier_fields=catalog_identifier_fields,
                        locked_mappings=locked_mappings,
                        auto_threshold=auto_threshold,
                        review_threshold=review_threshold,
                        disable_fuzzy=disable_fuzzy,
                    )

                    if match_result.is_auto_match and match_result.score >= auto_threshold:
                        existing_offer = self.matching_service._find_existing_offer(  # noqa: SLF001
                            conn,
                            advertiser_db_id=int(advertiser_row["id"]),
                            network_product_id=item.network_product_id,
                            merchant_product_id=item.merchant_product_id,
                        )
                        if existing_offer is None:
                            if len(report["warnings"]) < 10:
                                report["warnings"].append(
                                    "Confident match found without an existing affiliate offer for "
                                    f"raw_feed_item_id={item.raw_feed_item_id}."
                                )
                        else:
                            rows_confident_matched_existing_offer += 1
                        continue

                    if match_result.status == "needs_review":
                        rows_needs_review_from_matching += 1
                        candidate_decisions.append(
                            self._build_candidate_decision(
                                item=item,
                                status="needs_review",
                                match_result=match_result,
                                source_classification="needs_review",
                            )
                        )
                        continue

                    if match_result.status == "unmatched":
                        rows_unmatched_from_matching += 1
                        candidate_decisions.append(
                            self._build_candidate_decision(
                                item=item,
                                status="pending",
                                match_result=match_result,
                                source_classification="unmatched",
                            )
                        )

                aggregates = self._aggregate_decisions(candidate_decisions)
                dedupe_conflicts = sum(
                    max(aggregate.source_count - 1, 0) for aggregate in aggregates
                )
                estimated_status_counts = self._status_counts(aggregates)
                report.update(
                    {
                        "status": "success",
                        "import_run_id": import_run_id,
                        "advertiser_db_id": advertiser_row["id"],
                        "affiliate_feed_db_id": affiliate_feed_row["id"],
                        "normalized_rows_total": len(normalized_items),
                        "rows_actionable_input": rows_actionable_input,
                        "rows_confident_matched_existing_offer": (
                            rows_confident_matched_existing_offer
                        ),
                        "rows_needs_review_from_matching": rows_needs_review_from_matching,
                        "rows_unmatched_from_matching": rows_unmatched_from_matching,
                        "rows_excluded_total": rows_excluded_total,
                        "rows_excluded_considered": rows_excluded_considered,
                        "candidates_created": 0,
                        "candidates_updated": 0,
                        "candidates_unchanged": 0,
                        "candidates_ignored_existing_status": 0,
                        "candidates_rejected_not_perfume": estimated_status_counts.get(
                            "rejected_not_perfume",
                            0,
                        ),
                        "candidates_pending": estimated_status_counts.get("pending", 0),
                        "candidates_needs_review": estimated_status_counts.get(
                            "needs_review",
                            0,
                        ),
                        "candidate_status_counts": estimated_status_counts,
                        "dedupe_conflicts": dedupe_conflicts,
                    }
                )

                if dry_run:
                    report["candidates_created"] = len(aggregates)
                    report["sample_candidates_created"] = [
                        self._sample_candidate(aggregate.primary, aggregate.source_count)
                        for aggregate in aggregates[:5]
                    ]
                else:
                    (
                        created,
                        updated,
                        unchanged,
                        ignored_existing_status,
                        rejected_not_perfume,
                        pending_count,
                        needs_review_count,
                        sample_created,
                        sample_updated,
                        sample_ignored,
                    ) = self._persist_candidates(
                        conn,
                        advertiser_db_id=int(advertiser_row["id"]),
                        aggregates=aggregates,
                        network_feed_id=str(affiliate_feed_row["network_feed_id"]),
                    )
                    report["candidates_created"] = created
                    report["candidates_updated"] = updated
                    report["candidates_unchanged"] = unchanged
                    report["candidates_ignored_existing_status"] = ignored_existing_status
                    report["candidates_rejected_not_perfume"] = rejected_not_perfume
                    report["candidates_pending"] = pending_count
                    report["candidates_needs_review"] = needs_review_count
                    report["sample_candidates_created"] = sample_created
                    report["sample_candidates_updated"] = sample_updated
                    report["sample_ignored_existing_status"] = sample_ignored

                report_path = write_report(
                    self.settings.affiliate_data_dir,
                    "create_candidates",
                    report,
                )
                return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "create_candidates_error",
                report,
            )
            if report_path is not None:
                raise CandidateError(f"{message}. Report written to {report_path}") from exc
            raise CandidateError(message) from exc

    def sync_perfume_insert_candidates(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
        limit: int | None = None,
        report_dir: Path | None = None,
        only_statuses: list[str] | None = None,
    ) -> tuple[dict[str, object], Path]:
        self.db_service.require_database_url()

        selected_statuses = only_statuses or ["pending", "needs_review"]
        report_root = report_dir or self.settings.reports_dir
        report_root.mkdir(parents=True, exist_ok=True)
        report_stamp = _report_timestamp()
        markdown_path = report_root / f"sync_perfume_insert_candidates_{report_stamp}.md"
        safe_csv_path = (
            report_root / f"sync_perfume_insert_candidates_safe_new_{report_stamp}.csv"
        )
        json_path = report_root / f"sync_perfume_insert_candidates_{report_stamp}.json"
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "sync-perfume-insert-candidates",
            "network": "awin",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "dry_run": dry_run,
            "database_url_redacted": True,
            "selection_limit": limit,
            "only_statuses": selected_statuses,
            "candidates_analyzed": 0,
            "staging_inserted": 0,
            "staging_updated": 0,
            "staging_ignored_manual_status": 0,
            "staging_pending_refreshed": 0,
            "classification_counts": {},
            "top_brands": [],
            "safe_new_candidates_count": 0,
            "markdown_report_path": str(markdown_path),
            "safe_csv_path": str(safe_csv_path),
        }

        try:
            with self.db_service.connect() as conn:
                self._ensure_perfume_insert_candidates_table(conn)
                advertiser_row, affiliate_feed_row = self.matching_service._resolve_feed_context(  # noqa: SLF001
                    conn,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )
                source_candidates = self._load_sync_source_candidates(
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    network_feed_id=str(affiliate_feed_row["network_feed_id"]),
                    only_statuses=selected_statuses,
                    limit=limit,
                )
                catalog_rows, available_catalog_columns = (
                    self.matching_service._load_catalog_perfumes(conn)  # noqa: SLF001
                )
                classifications = self._classify_insert_candidates(
                    source_candidates,
                    catalog_rows=catalog_rows,
                    available_catalog_columns=available_catalog_columns,
                )
                brand_counts = Counter(
                    entry.candidate_brand or "<missing>" for entry in classifications
                )
                classification_counts = Counter(
                    entry.classification for entry in classifications
                )
                report.update(
                    {
                        "status": "success",
                        "candidates_analyzed": len(classifications),
                        "classification_counts": dict(sorted(classification_counts.items())),
                        "top_brands": [
                            {"candidate_brand": brand, "count": count}
                            for brand, count in brand_counts.most_common(10)
                        ],
                    }
                )

                if dry_run:
                    (
                        inserted,
                        updated,
                        ignored_manual,
                        pending_refreshed,
                        safe_candidates,
                    ) = self._plan_insert_candidate_sync(conn, classifications=classifications)
                    report["staging_inserted"] = inserted
                    report["staging_updated"] = updated
                    report["staging_ignored_manual_status"] = ignored_manual
                    report["staging_pending_refreshed"] = pending_refreshed
                    report["safe_new_candidates_count"] = len(safe_candidates)
                    self._write_sync_markdown(markdown_path, report)
                    self._write_sync_safe_csv(safe_csv_path, safe_candidates)
                else:
                    (
                        inserted,
                        updated,
                        ignored_manual,
                        pending_refreshed,
                        safe_candidates,
                    ) = self._persist_insert_candidates(conn, classifications=classifications)
                    report["staging_inserted"] = inserted
                    report["staging_updated"] = updated
                    report["staging_ignored_manual_status"] = ignored_manual
                    report["staging_pending_refreshed"] = pending_refreshed
                    report["safe_new_candidates_count"] = len(safe_candidates)
                    self._write_sync_markdown(markdown_path, report)
                    self._write_sync_safe_csv(safe_csv_path, safe_candidates)

            json_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return report, json_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            try:
                json_path.write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            raise CandidateError(message) from exc

    def refresh_product_match_candidates(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
        limit: int | None = None,
        report_dir: Path | None = None,
        only_statuses: list[str] | None = None,
        brand: str | None = None,
        min_score: int | None = None,
    ) -> tuple[dict[str, object], Path]:
        self.db_service.require_database_url()

        selected_statuses = only_statuses or ["pending", "needs_review"]
        report_root = report_dir or self.settings.reports_dir
        report_root.mkdir(parents=True, exist_ok=True)
        report_stamp = _report_timestamp()
        markdown_path = report_root / f"refresh_product_match_candidates_{report_stamp}.md"
        csv_path = report_root / f"refresh_product_match_candidates_updates_{report_stamp}.csv"
        json_path = report_root / f"refresh_product_match_candidates_{report_stamp}.json"
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "refresh-product-match-candidates",
            "network": "awin",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "dry_run": dry_run,
            "database_url_redacted": True,
            "selection_limit": limit,
            "brand": brand,
            "min_score": min_score,
            "only_statuses": selected_statuses,
            "candidates_loaded": 0,
            "candidates_evaluated": 0,
            "candidates_updated": 0,
            "candidates_unchanged": 0,
            "candidates_without_match": 0,
            "candidates_ignored_closed_status": 0,
            "top_brands": [],
            "status_counts_before": {},
            "status_counts_after": {},
            "sample_updates": [],
            "markdown_report_path": str(markdown_path),
            "csv_report_path": str(csv_path),
        }

        try:
            with self.db_service.connect() as conn:
                advertiser_row, affiliate_feed_row = self.matching_service._resolve_feed_context(  # noqa: SLF001
                    conn,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )
                source_candidates = self._load_refresh_source_candidates(
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    network_feed_id=str(affiliate_feed_row["network_feed_id"]),
                    only_statuses=selected_statuses,
                    brand=brand,
                    limit=limit,
                )
                catalog_rows, available_catalog_columns = (
                    self.matching_service._load_catalog_perfumes(conn)  # noqa: SLF001
                )
                locked_mappings = self.matching_service._load_locked_mappings(  # noqa: SLF001
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    auto_threshold=int(self.settings.affiliate_match_auto_threshold),
                )
                catalog_identifier_fields = [
                    field
                    for field in ("ean", "gtin", "upc", "mpn")
                    if field in available_catalog_columns
                ]
                catalog_by_brand: dict[str, list[CatalogPerfume]] = {}
                for perfume in catalog_rows:
                    catalog_by_brand.setdefault(perfume.normalized_brand, []).append(perfume)

                evaluations: list[CandidateRefreshEvaluation] = []
                for source in source_candidates:
                    evaluations.append(
                        self._evaluate_candidate_refresh(
                            source,
                            affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                            catalog_rows=catalog_rows,
                            catalog_by_brand=catalog_by_brand,
                            catalog_identifier_fields=catalog_identifier_fields,
                            locked_mappings=locked_mappings,
                            auto_threshold=int(self.settings.affiliate_match_auto_threshold),
                            review_threshold=int(
                                self.settings.affiliate_match_review_threshold
                            ),
                            min_score=min_score,
                        )
                    )

                action_counts = Counter(entry.action for entry in evaluations)
                brand_counts = Counter(
                    (entry.candidate_brand or "<missing>") for entry in evaluations
                )
                status_counts_before = Counter(entry.status_before for entry in evaluations)
                status_counts_after = Counter(entry.status_after for entry in evaluations)
                report.update(
                    {
                        "status": "success",
                        "candidates_loaded": len(source_candidates),
                        "candidates_evaluated": len(evaluations),
                        "candidates_updated": action_counts.get("update", 0),
                        "candidates_unchanged": action_counts.get("unchanged", 0),
                        "candidates_without_match": action_counts.get("no_match", 0),
                        "candidates_ignored_closed_status": action_counts.get(
                            "ignored_closed_status",
                            0,
                        ),
                        "top_brands": [
                            {"candidate_brand": brand_name, "count": count}
                            for brand_name, count in brand_counts.most_common(10)
                        ],
                        "status_counts_before": dict(sorted(status_counts_before.items())),
                        "status_counts_after": dict(sorted(status_counts_after.items())),
                        "sample_updates": [
                            entry.as_csv_row()
                            for entry in evaluations
                            if entry.action == "update"
                        ][:10],
                    }
                )

                if not dry_run:
                    self._persist_candidate_refreshes(conn, evaluations=evaluations)

                self._write_refresh_markdown(markdown_path, report)
                self._write_refresh_csv(csv_path, evaluations)

            json_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return report, json_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            try:
                json_path.write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            raise CandidateError(message) from exc

    def _ensure_candidate_dedupe_column(self, conn: Any) -> None:
        row = conn.execute(
            """
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'product_match_candidates'
              and column_name = 'dedupe_key'
            """
        ).fetchone()
        if row is None:
            raise CandidateError(
                "product_match_candidates.dedupe_key is missing. "
                "Run migrate-db from PR08 first."
            )

    def _ensure_perfume_insert_candidates_table(self, conn: Any) -> None:
        required_columns = {
            "id",
            "source_candidate_id",
            "candidate_brand",
            "candidate_name",
            "classification",
            "review_status",
            "first_seen_at",
            "last_seen_at",
            "seen_count",
            "promoted_at",
            "promoted_perfume_id",
            "updated_at",
        }
        rows = conn.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'perfume_insert_candidates'
            """
        ).fetchall()
        available = {str(row["column_name"]) for row in rows}
        missing = sorted(required_columns - available)
        if missing:
            raise CandidateError(
                "public.perfume_insert_candidates is missing required columns: "
                + ", ".join(missing)
            )

    def _load_sync_source_candidates(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        network_feed_id: str,
        only_statuses: list[str],
        limit: int | None,
    ) -> list[dict[str, object]]:
        sql = """
            select *
            from product_match_candidates
            where advertiser_id = %s
              and status = any(%s)
              and coalesce(enrichment_payload ->> 'network_feed_id', '') = %s
            order by id
        """
        params: list[object] = [advertiser_db_id, only_statuses, network_feed_id]
        if limit is not None:
            sql += " limit %s"
            params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def _load_refresh_source_candidates(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        network_feed_id: str,
        only_statuses: list[str],
        brand: str | None,
        limit: int | None,
    ) -> list[dict[str, object]]:
        sql = """
            select *
            from product_match_candidates
            where advertiser_id = %s
              and status = any(%s)
              and coalesce(enrichment_payload ->> 'network_feed_id', '') = %s
        """
        params: list[object] = [advertiser_db_id, only_statuses, network_feed_id]
        if brand:
            sql += " and lower(coalesce(candidate_brand, '')) = lower(%s)"
            params.append(brand)
        sql += " order by id"
        if limit is not None:
            sql += " limit %s"
            params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def _classify_insert_candidates(
        self,
        source_candidates: list[dict[str, object]],
        *,
        catalog_rows: list[CatalogPerfume],
        available_catalog_columns: set[str],
    ) -> list[InsertCandidateClassification]:
        catalog_by_brand: dict[str, list[CatalogPerfume]] = {}
        identifiers_by_field: dict[str, dict[str, list[CatalogPerfume]]] = {
            field: {} for field in ("ean", "gtin", "upc", "mpn")
        }
        for perfume in catalog_rows:
            catalog_by_brand.setdefault(perfume.normalized_brand, []).append(perfume)
            for field, value in perfume.identifiers.items():
                identifiers_by_field[field].setdefault(value, []).append(perfume)

        classifications: list[InsertCandidateClassification] = []
        for source in source_candidates:
            enrichment = dict(source.get("enrichment_payload") or {})
            candidate_brand = source.get("candidate_brand")
            candidate_name = str(source["candidate_name"])
            candidate_concentration = source.get("candidate_concentration")
            candidate_volume_ml = source.get("candidate_volume_ml")
            candidate_category = source.get("candidate_category")
            candidate_image_url = source.get("candidate_image_url")
            candidate_affiliate_url = (
                enrichment.get("affiliate_url") or source.get("candidate_url")
            )
            candidate_source_title = enrichment.get("title") or candidate_name
            candidate_ean = _identifier_value(enrichment.get("ean"))
            candidate_gtin = _identifier_value(enrichment.get("gtin"))
            candidate_upc = _identifier_value(enrichment.get("upc"))
            candidate_mpn = _identifier_value(enrichment.get("mpn"))
            candidate_identifier_map = {
                "ean": candidate_ean,
                "gtin": candidate_gtin,
                "upc": candidate_upc,
                "mpn": candidate_mpn,
            }

            nearest_perfume: CatalogPerfume | None = None
            duplicate_reason: str | None = None
            duplicate_risk: str | None = None
            classification = NEEDS_MANUAL_REVIEW
            confidence = Decimal("0.5000")

            if self._is_non_perfume_candidate(
                candidate_name=candidate_name,
                source_title=str(candidate_source_title) if candidate_source_title else None,
                candidate_category=str(candidate_category) if candidate_category else None,
            ):
                classification = NON_PERFUME_PRODUCT
                confidence = Decimal("0.9800")
                duplicate_risk = None
                duplicate_reason = "Detected non-perfume keywords in title or category."
            else:
                exact_identifier_match = self._find_identifier_duplicate(
                    candidate_identifier_map,
                    identifiers_by_field=identifiers_by_field,
                )
                if exact_identifier_match is not None:
                    nearest_perfume = exact_identifier_match
                    classification = POSSIBLE_DUPLICATE
                    confidence = Decimal("0.9900")
                    duplicate_risk = "high"
                    duplicate_reason = "Identifier already exists in public.perfumes."
                else:
                    normalized_brand = normalize_text(candidate_brand)
                    normalized_name = normalize_text(candidate_name)
                    candidate_key = build_perfume_match_key(
                        candidate_name,
                        brand=str(candidate_brand) if candidate_brand else None,
                        concentration=(
                            str(candidate_concentration)
                            if candidate_concentration is not None
                            else None
                        ),
                        volume_ml=candidate_volume_ml,
                    )
                    brand_catalog = catalog_by_brand.get(normalized_brand, [])
                    exact_name_match = next(
                        (
                            perfume
                            for perfume in brand_catalog
                            if normalize_text(perfume.name) == normalized_name
                        ),
                        None,
                    )
                    if exact_name_match is not None:
                        nearest_perfume = exact_name_match
                        classification = POSSIBLE_DUPLICATE
                        confidence = Decimal("0.9700")
                        duplicate_risk = "high"
                        duplicate_reason = "Exact brand/name match already exists."
                    else:
                        key_match = next(
                            (
                                perfume
                                for perfume in brand_catalog
                                if candidate_key and perfume.match_key == candidate_key
                            ),
                            None,
                        )
                        if key_match is not None:
                            nearest_perfume = key_match
                            classification = VARIANT_OF_EXISTING
                            confidence = Decimal("0.9200")
                            duplicate_risk = "medium"
                            duplicate_reason = (
                                "Normalized perfume name matches an existing brand variant."
                            )
                        elif source.get("proposed_perfume_id") is not None:
                            nearest_perfume = next(
                                (
                                    perfume
                                    for perfume in catalog_rows
                                    if perfume.id == str(source["proposed_perfume_id"])
                                ),
                                None,
                            )
                            classification = VARIANT_OF_EXISTING
                            confidence = Decimal("0.8500")
                            duplicate_risk = "medium"
                            duplicate_reason = (
                                "Candidate already points to an existing perfume proposal."
                            )
                        elif not candidate_brand or not candidate_name:
                            classification = NEEDS_MANUAL_REVIEW
                            confidence = Decimal("0.4000")
                            duplicate_risk = "unknown"
                            duplicate_reason = "Missing brand or candidate name."
                        elif not brand_catalog:
                            classification = SAFE_INSERT_CANDIDATE
                            confidence = Decimal("0.9000")
                            duplicate_risk = "low"
                            duplicate_reason = "Brand does not exist in public.perfumes."
                        else:
                            classification = NEEDS_MANUAL_REVIEW
                            confidence = Decimal("0.6500")
                            duplicate_risk = "medium"
                            duplicate_reason = (
                                "Brand exists, but automated duplicate checks remain inconclusive."
                            )

            classifications.append(
                InsertCandidateClassification(
                    source_candidate_id=int(source["id"]),
                    source_offer_id=None,
                    candidate_brand=str(candidate_brand) if candidate_brand else None,
                    candidate_name=candidate_name,
                    candidate_concentration=(
                        str(candidate_concentration)
                        if candidate_concentration is not None
                        else None
                    ),
                    candidate_volume_ml=candidate_volume_ml,
                    candidate_category=str(candidate_category) if candidate_category else None,
                    candidate_ean=candidate_ean,
                    candidate_gtin=candidate_gtin,
                    candidate_upc=candidate_upc,
                    candidate_mpn=candidate_mpn,
                    candidate_image_url=(
                        str(candidate_image_url) if candidate_image_url else None
                    ),
                    candidate_source_title=(
                        str(candidate_source_title) if candidate_source_title else None
                    ),
                    candidate_affiliate_url=(
                        str(candidate_affiliate_url) if candidate_affiliate_url else None
                    ),
                    classification=classification,
                    confidence=confidence,
                    duplicate_risk=duplicate_risk,
                    duplicate_reason=duplicate_reason,
                    nearest_perfume_id=nearest_perfume.id if nearest_perfume else None,
                    nearest_perfume_brand=nearest_perfume.brand if nearest_perfume else None,
                    nearest_perfume_name=nearest_perfume.name if nearest_perfume else None,
                    source_status=str(source["status"]),
                )
            )
        return classifications

    def _evaluate_candidate_refresh(
        self,
        source: dict[str, object],
        *,
        affiliate_feed_db_id: int,
        catalog_rows: list[CatalogPerfume],
        catalog_by_brand: dict[str, list[CatalogPerfume]],
        catalog_identifier_fields: list[str],
        locked_mappings: list[object],
        auto_threshold: int,
        review_threshold: int,
        min_score: int | None,
    ) -> CandidateRefreshEvaluation:
        status_before = str(source["status"])
        proposed_before = (
            str(source["proposed_perfume_id"])
            if source.get("proposed_perfume_id") is not None
            else None
        )
        score_before = (
            Decimal(str(source["match_score"]))
            if source.get("match_score") is not None
            else None
        )
        reason_before = (
            str(source["match_reason"]) if source.get("match_reason") is not None else None
        )

        if status_before not in AUTO_MUTABLE_CANDIDATE_STATUSES:
            return CandidateRefreshEvaluation(
                candidate_id=int(source["id"]),
                candidate_brand=(
                    str(source["candidate_brand"])
                    if source.get("candidate_brand") is not None
                    else None
                ),
                candidate_name=str(source["candidate_name"]),
                status_before=status_before,
                status_after=status_before,
                proposed_perfume_id_before=proposed_before,
                proposed_perfume_id_after=proposed_before,
                match_score_before=score_before,
                match_score_after=score_before,
                match_reason_before=reason_before,
                match_reason_after=reason_before,
                source_import_run_id=_int_from_value(
                    dict(source.get("enrichment_payload") or {}).get("import_run_id")
                ),
                source_network_product_id=_identifier_value(
                    dict(source.get("enrichment_payload") or {}).get("network_product_id")
                ),
                source_merchant_product_id=_identifier_value(
                    dict(source.get("enrichment_payload") or {}).get("merchant_product_id")
                ),
                action="ignored_closed_status",
            )

        item = self._rebuild_refresh_item(
            source,
            affiliate_feed_db_id=affiliate_feed_db_id,
        )
        match_result = self.matching_service._match_item(  # noqa: SLF001
            item,
            catalog_rows=catalog_rows,
            catalog_by_brand=catalog_by_brand,
            catalog_identifier_fields=catalog_identifier_fields,
            locked_mappings=locked_mappings,
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
            disable_fuzzy=False,
        )
        score_after = (
            Decimal(str(match_result.score)) if match_result.score > 0 else None
        )
        proposed_after = match_result.perfume_id
        action = self._decide_candidate_refresh_action(
            status_before=status_before,
            proposed_before=proposed_before,
            score_before=score_before,
            proposed_after=proposed_after,
            score_after=score_after,
            min_score=min_score,
        )
        status_after = status_before
        reason_after = reason_before
        if action == "update":
            status_after = "needs_review"
            reason_after = match_result.match_reason
        elif action == "no_match":
            reason_after = match_result.match_reason
        return CandidateRefreshEvaluation(
            candidate_id=int(source["id"]),
            candidate_brand=(
                str(source["candidate_brand"]) if source.get("candidate_brand") else None
            ),
            candidate_name=str(source["candidate_name"]),
            status_before=status_before,
            status_after=status_after,
            proposed_perfume_id_before=proposed_before,
            proposed_perfume_id_after=proposed_after if action == "update" else proposed_before,
            match_score_before=score_before,
            match_score_after=score_after if action == "update" else score_before,
            match_reason_before=reason_before,
            match_reason_after=reason_after,
            source_import_run_id=_int_from_value(
                dict(source.get("enrichment_payload") or {}).get("import_run_id")
            ),
            source_network_product_id=_identifier_value(
                dict(source.get("enrichment_payload") or {}).get("network_product_id")
            ),
            source_merchant_product_id=_identifier_value(
                dict(source.get("enrichment_payload") or {}).get("merchant_product_id")
            ),
            action=action,
        )

    def _rebuild_refresh_item(
        self,
        source: dict[str, object],
        *,
        affiliate_feed_db_id: int,
    ) -> LoadedNormalizedItem:
        enrichment = dict(source.get("enrichment_payload") or {})
        brand = (
            str(source["candidate_brand"])
            if source.get("candidate_brand") is not None
            else _identifier_value(enrichment.get("brand"))
        )
        title = _identifier_value(enrichment.get("title")) or str(source["candidate_name"])
        concentration = (
            str(source["candidate_concentration"])
            if source.get("candidate_concentration") is not None
            else _identifier_value(enrichment.get("concentration"))
        )
        volume_ml = source.get("candidate_volume_ml")
        if volume_ml is None:
            volume_ml = _decimal_from_value(enrichment.get("volume_ml"))
        network_product_id = _identifier_value(enrichment.get("network_product_id"))
        merchant_product_id = _identifier_value(enrichment.get("merchant_product_id"))
        candidate_url = (
            _identifier_value(source.get("candidate_url"))
            or _identifier_value(enrichment.get("affiliate_url"))
            or _identifier_value(enrichment.get("merchant_url"))
        )
        image_url = (
            _identifier_value(source.get("candidate_image_url"))
            or _identifier_value(enrichment.get("image_url"))
        )
        category = (
            str(source["candidate_category"])
            if source.get("candidate_category") is not None
            else _identifier_value(enrichment.get("category"))
        )
        normalized_title = _identifier_value(enrichment.get("normalized_title")) or normalize_text(
            title
        )
        normalized_brand = _identifier_value(
            enrichment.get("normalized_brand")
        ) or normalize_text(brand)
        normalized_category = normalize_text(category)
        price = _decimal_from_value(enrichment.get("price"))
        raw_payload = dict(enrichment.get("raw_payload") or enrichment)
        return LoadedNormalizedItem(
            id=_int_from_value(enrichment.get("normalized_feed_item_id")) or int(source["id"]),
            raw_feed_item_id=_int_from_value(source.get("raw_feed_item_id"))
            or _int_from_value(enrichment.get("raw_feed_item_id"))
            or int(source["id"]),
            raw_hash=_identifier_value(enrichment.get("raw_hash")) or f"candidate:{source['id']}",
            import_run_id=_int_from_value(enrichment.get("import_run_id")) or 0,
            advertiser_id=int(source["advertiser_id"]),
            feed_id=affiliate_feed_db_id,
            network=_identifier_value(enrichment.get("network")) or "awin",
            network_product_id=network_product_id,
            merchant_product_id=merchant_product_id,
            title=title,
            normalized_title=normalized_title,
            description=_identifier_value(enrichment.get("description")),
            brand=brand,
            normalized_brand=normalized_brand or None,
            category=category,
            normalized_category=normalized_category or None,
            price=price,
            currency=_identifier_value(enrichment.get("currency")),
            delivery_cost=_decimal_from_value(enrichment.get("delivery_cost")),
            affiliate_url=candidate_url,
            merchant_url=_identifier_value(enrichment.get("merchant_url")),
            image_url=image_url,
            ean=_identifier_value(enrichment.get("ean")),
            gtin=_identifier_value(enrichment.get("gtin")),
            upc=_identifier_value(enrichment.get("upc")),
            mpn=_identifier_value(enrichment.get("mpn")),
            in_stock=None,
            stock_status=_identifier_value(enrichment.get("stock_status")),
            concentration=concentration,
            volume_ml=volume_ml,
            is_fragrance=True,
            is_excluded=False,
            exclusion_reasons=[],
            missing_required_columns=[],
            missing_recommended_columns=[],
            normalized_payload=dict(enrichment),
            raw_payload=raw_payload,
            match_key=build_perfume_match_key(
                title,
                brand=brand,
                concentration=concentration,
                volume_ml=volume_ml,
            ),
        )

    def _decide_candidate_refresh_action(
        self,
        *,
        status_before: str,
        proposed_before: str | None,
        score_before: Decimal | None,
        proposed_after: str | None,
        score_after: Decimal | None,
        min_score: int | None,
    ) -> str:
        if status_before not in AUTO_MUTABLE_CANDIDATE_STATUSES:
            return "ignored_closed_status"
        if proposed_after is None:
            return "no_match"
        if min_score is not None:
            comparable_score = float(score_after or Decimal("0"))
            if comparable_score < float(min_score):
                return "unchanged"
        if proposed_before is None:
            return "update"
        if score_before is None:
            return "update"
        if score_after is None:
            return "unchanged"
        if proposed_before != proposed_after and score_after > score_before:
            return "update"
        if proposed_before == proposed_after and score_after > score_before:
            return "update"
        return "unchanged"

    def _persist_candidate_refreshes(
        self,
        conn: Any,
        *,
        evaluations: list[CandidateRefreshEvaluation],
    ) -> None:
        with conn.transaction():
            for evaluation in evaluations:
                if evaluation.action != "update":
                    continue
                existing = conn.execute(
                    """
                    select enrichment_payload
                    from product_match_candidates
                    where id = %s
                    """,
                    (evaluation.candidate_id,),
                ).fetchone()
                enrichment_payload = (
                    dict(existing["enrichment_payload"])
                    if existing is not None and existing["enrichment_payload"] is not None
                    else {}
                )
                enrichment_payload["refresh_command"] = "refresh-product-match-candidates"
                enrichment_payload["refresh_checked_at"] = _utc_now()
                conn.execute(
                    """
                    update product_match_candidates
                    set proposed_perfume_id = %s,
                        match_score = %s,
                        match_reason = %s,
                        status = %s,
                        enrichment_payload = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        evaluation.proposed_perfume_id_after,
                        evaluation.match_score_after,
                        evaluation.match_reason_after,
                        evaluation.status_after,
                        Jsonb(enrichment_payload),
                        evaluation.candidate_id,
                    ),
                )

    def _write_refresh_markdown(
        self,
        markdown_path: Path,
        report: Mapping[str, object],
    ) -> None:
        lines = [
            "# refresh-product-match-candidates",
            "",
            f"- status: `{report.get('status')}`",
            f"- dry_run: `{report.get('dry_run')}`",
            f"- advertiser_id: `{report.get('advertiser_id')}`",
            f"- feed_id: `{report.get('feed_id')}`",
            f"- brand: `{report.get('brand') or '*'} `",
            f"- candidates_loaded: `{report.get('candidates_loaded')}`",
            f"- candidates_updated: `{report.get('candidates_updated')}`",
            f"- candidates_without_match: `{report.get('candidates_without_match')}`",
            f"- candidates_unchanged: `{report.get('candidates_unchanged')}`",
            (
                "- candidates_ignored_closed_status: "
                f"`{report.get('candidates_ignored_closed_status')}`"
            ),
            "",
            "## Status counts before",
            "",
        ]
        for status_name, count in (report.get("status_counts_before") or {}).items():
            lines.append(f"- `{status_name}`: `{count}`")
        lines.extend(["", "## Status counts after", ""])
        for status_name, count in (report.get("status_counts_after") or {}).items():
            lines.append(f"- `{status_name}`: `{count}`")
        lines.extend(["", "## Top brands", ""])
        top_brands = report.get("top_brands") or []
        if top_brands:
            for row in top_brands:
                lines.append(f"- `{row.get('candidate_brand')}`: `{row.get('count')}`")
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "## Safety",
                "",
                "- This command updates only `public.product_match_candidates`.",
                "- It never promotes candidates into `public.perfumes`.",
                "- It never links or mutates `public.offers`.",
                "- Open candidates with a new match are moved to `needs_review` conservatively.",
                "",
            ]
        )
        markdown_path.write_text("\n".join(lines), encoding="utf-8")

    def _write_refresh_csv(
        self,
        csv_path: Path,
        evaluations: list[CandidateRefreshEvaluation],
    ) -> None:
        fieldnames = [
            "candidate_id",
            "candidate_brand",
            "candidate_name",
            "status_before",
            "status_after",
            "proposed_perfume_id_before",
            "proposed_perfume_id_after",
            "match_score_before",
            "match_score_after",
            "match_reason_before",
            "match_reason_after",
            "source_import_run_id",
            "source_network_product_id",
            "source_merchant_product_id",
            "action",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for evaluation in evaluations:
                writer.writerow(evaluation.as_csv_row())

    def _is_non_perfume_candidate(
        self,
        *,
        candidate_name: str,
        source_title: str | None,
        candidate_category: str | None,
    ) -> bool:
        blob = _build_text_blob(candidate_name, source_title, candidate_category)
        return any(keyword in blob for keyword in NON_PERFUME_PATTERNS)

    def _find_identifier_duplicate(
        self,
        candidate_identifier_map: dict[str, str | None],
        *,
        identifiers_by_field: dict[str, dict[str, list[CatalogPerfume]]],
    ) -> CatalogPerfume | None:
        for field, value in candidate_identifier_map.items():
            if not value:
                continue
            matches = identifiers_by_field[field].get(value, [])
            if len(matches) == 1:
                return matches[0]
        return None

    def _load_existing_insert_candidate(
        self,
        conn: Any,
        *,
        source_candidate_id: int,
    ) -> dict[str, object] | None:
        row = conn.execute(
            """
            select *
            from perfume_insert_candidates
            where source_candidate_id = %s
            """,
            (source_candidate_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _persist_insert_candidates(
        self,
        conn: Any,
        *,
        classifications: list[InsertCandidateClassification],
    ) -> tuple[int, int, int, int, list[InsertCandidateClassification]]:
        inserted = 0
        updated = 0
        ignored_manual = 0
        pending_refreshed = 0
        safe_new_candidates: list[InsertCandidateClassification] = []

        with conn.transaction():
            for entry in classifications:
                existing = self._load_existing_insert_candidate(
                    conn,
                    source_candidate_id=entry.source_candidate_id,
                )
                if existing is None:
                    conn.execute(
                        """
                        insert into perfume_insert_candidates (
                            source_candidate_id,
                            source_offer_id,
                            candidate_brand,
                            candidate_name,
                            candidate_concentration,
                            candidate_volume_ml,
                            candidate_category,
                            candidate_ean,
                            candidate_gtin,
                            candidate_upc,
                            candidate_mpn,
                            candidate_image_url,
                            candidate_source_title,
                            candidate_affiliate_url,
                            classification,
                            confidence,
                            duplicate_risk,
                            duplicate_reason,
                            nearest_perfume_id,
                            nearest_perfume_brand,
                            nearest_perfume_name,
                            review_status,
                            first_seen_at,
                            last_seen_at,
                            seen_count,
                            updated_at
                        )
                        values (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, 'pending', now(), now(), 1, now()
                        )
                        """,
                        (
                            entry.source_candidate_id,
                            entry.source_offer_id,
                            entry.candidate_brand,
                            entry.candidate_name,
                            entry.candidate_concentration,
                            entry.candidate_volume_ml,
                            entry.candidate_category,
                            entry.candidate_ean,
                            entry.candidate_gtin,
                            entry.candidate_upc,
                            entry.candidate_mpn,
                            entry.candidate_image_url,
                            entry.candidate_source_title,
                            entry.candidate_affiliate_url,
                            entry.classification,
                            entry.confidence,
                            entry.duplicate_risk,
                            entry.duplicate_reason,
                            entry.nearest_perfume_id,
                            entry.nearest_perfume_brand,
                            entry.nearest_perfume_name,
                        ),
                    )
                    inserted += 1
                    if entry.classification == SAFE_INSERT_CANDIDATE:
                        safe_new_candidates.append(entry)
                    continue

                review_status = str(existing["review_status"])
                if review_status in STAGING_FINAL_REVIEW_STATUSES:
                    conn.execute(
                        """
                        update perfume_insert_candidates
                        set last_seen_at = now(),
                            seen_count = coalesce(seen_count, 0) + 1,
                            updated_at = now()
                        where id = %s
                        """,
                        (existing["id"],),
                    )
                    ignored_manual += 1
                    continue

                conn.execute(
                    """
                    update perfume_insert_candidates
                    set candidate_brand = %s,
                        candidate_name = %s,
                        candidate_concentration = %s,
                        candidate_volume_ml = %s,
                        candidate_category = %s,
                        candidate_ean = %s,
                        candidate_gtin = %s,
                        candidate_upc = %s,
                        candidate_mpn = %s,
                        candidate_image_url = %s,
                        candidate_source_title = %s,
                        candidate_affiliate_url = %s,
                        classification = %s,
                        confidence = %s,
                        duplicate_risk = %s,
                        duplicate_reason = %s,
                        nearest_perfume_id = %s,
                        nearest_perfume_brand = %s,
                        nearest_perfume_name = %s,
                        last_seen_at = now(),
                        seen_count = coalesce(seen_count, 0) + 1,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        entry.candidate_brand,
                        entry.candidate_name,
                        entry.candidate_concentration,
                        entry.candidate_volume_ml,
                        entry.candidate_category,
                        entry.candidate_ean,
                        entry.candidate_gtin,
                        entry.candidate_upc,
                        entry.candidate_mpn,
                        entry.candidate_image_url,
                        entry.candidate_source_title,
                        entry.candidate_affiliate_url,
                        entry.classification,
                        entry.confidence,
                        entry.duplicate_risk,
                        entry.duplicate_reason,
                        entry.nearest_perfume_id,
                        entry.nearest_perfume_brand,
                        entry.nearest_perfume_name,
                        existing["id"],
                    ),
                )
                updated += 1
                pending_refreshed += 1

        return inserted, updated, ignored_manual, pending_refreshed, safe_new_candidates

    def _plan_insert_candidate_sync(
        self,
        conn: Any,
        *,
        classifications: list[InsertCandidateClassification],
    ) -> tuple[int, int, int, int, list[InsertCandidateClassification]]:
        inserted = 0
        updated = 0
        ignored_manual = 0
        pending_refreshed = 0
        safe_new_candidates: list[InsertCandidateClassification] = []

        for entry in classifications:
            existing = self._load_existing_insert_candidate(
                conn,
                source_candidate_id=entry.source_candidate_id,
            )
            if existing is None:
                inserted += 1
                if entry.classification == SAFE_INSERT_CANDIDATE:
                    safe_new_candidates.append(entry)
                continue

            review_status = str(existing["review_status"])
            if review_status in STAGING_FINAL_REVIEW_STATUSES:
                ignored_manual += 1
            else:
                updated += 1
                pending_refreshed += 1

        return inserted, updated, ignored_manual, pending_refreshed, safe_new_candidates

    def _write_sync_markdown(self, markdown_path: Path, report: Mapping[str, object]) -> None:
        lines = [
            "# sync-perfume-insert-candidates",
            "",
            f"- status: `{report.get('status')}`",
            f"- dry_run: `{report.get('dry_run')}`",
            f"- advertiser_id: `{report.get('advertiser_id')}`",
            f"- feed_id: `{report.get('feed_id')}`",
            f"- candidates_analyzed: `{report.get('candidates_analyzed')}`",
            f"- staging_inserted: `{report.get('staging_inserted')}`",
            f"- staging_updated: `{report.get('staging_updated')}`",
            f"- staging_ignored_manual_status: `{report.get('staging_ignored_manual_status')}`",
            f"- safe_new_candidates_count: `{report.get('safe_new_candidates_count')}`",
            "",
            "## Classification counts",
            "",
        ]
        classification_counts = report.get("classification_counts") or {}
        if classification_counts:
            for classification, count in classification_counts.items():
                lines.append(f"- `{classification}`: `{count}`")
        else:
            lines.append("- none")
        lines.extend(["", "## Top brands", ""])
        top_brands = report.get("top_brands") or []
        if top_brands:
            for row in top_brands:
                lines.append(
                    f"- `{row.get('candidate_brand')}`: `{row.get('count')}`"
                )
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "## Safety",
                "",
                "- This command updates only `public.perfume_insert_candidates`.",
                "- It never promotes candidates into `public.perfumes`.",
                "- Manual review statuses remain unchanged.",
                "",
            ]
        )
        markdown_path.write_text("\n".join(lines), encoding="utf-8")

    def _write_sync_safe_csv(
        self,
        safe_csv_path: Path,
        safe_candidates: list[InsertCandidateClassification],
    ) -> None:
        fieldnames = [
            "source_candidate_id",
            "candidate_brand",
            "candidate_name",
            "candidate_concentration",
            "candidate_volume_ml",
            "candidate_ean",
            "candidate_gtin",
            "candidate_upc",
            "candidate_mpn",
            "candidate_image_url",
            "candidate_source_title",
            "classification",
            "confidence",
            "duplicate_risk",
            "duplicate_reason",
            "nearest_perfume_id",
            "nearest_perfume_brand",
            "nearest_perfume_name",
            "source_status",
        ]
        with safe_csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for entry in safe_candidates:
                writer.writerow(entry.as_csv_row())

    def _build_excluded_decision(
        self,
        conn: Any,
        *,
        item: LoadedNormalizedItem,
        advertiser_db_id: int,
        catalog_rows: list[object],
        catalog_by_brand: dict[str, list[object]],
        catalog_identifier_fields: list[str],
        locked_mappings: list[object],
        auto_threshold: int,
        review_threshold: int,
        disable_fuzzy: bool,
        include_excluded: bool,
    ) -> CandidateDecision | None:
        reasons = set(item.exclusion_reasons)
        if reasons & COMMERCIAL_EXCLUDED_REASONS:
            match_result = self._match_result_for_excluded_item(
                item=item,
                catalog_rows=catalog_rows,
                catalog_by_brand=catalog_by_brand,
                catalog_identifier_fields=catalog_identifier_fields,
                locked_mappings=locked_mappings,
                auto_threshold=auto_threshold,
                review_threshold=review_threshold,
                disable_fuzzy=disable_fuzzy,
            )
            label = "excluded_set_or_bundle" if "set_or_bundle" in reasons else "excluded_refill"
            match_reason = label
            if match_result is not None and match_result.perfume_id is not None:
                match_reason = f"{label}; {match_result.match_reason}"
            return self._build_candidate_decision(
                item=item,
                status="needs_review",
                match_result=match_result,
                source_classification="excluded_commercial",
                explicit_match_reason=match_reason,
            )

        if reasons & REJECTED_EXCLUDED_REASONS:
            if not include_excluded:
                return None
            label = (
                "excluded_body_product"
                if "body_product" in reasons
                else "excluded_home_fragrance"
            )
            return self._build_candidate_decision(
                item=item,
                status="rejected_not_perfume",
                match_result=None,
                source_classification="excluded_rejected",
                explicit_match_reason=label,
            )

        if reasons & IGNORED_EXCLUDED_REASONS:
            if not include_excluded:
                return None
            return self._build_candidate_decision(
                item=item,
                status="ignored",
                match_result=None,
                source_classification="excluded_ignored",
                explicit_match_reason="excluded_tester",
            )

        return None

    def _match_result_for_excluded_item(
        self,
        *,
        item: LoadedNormalizedItem,
        catalog_rows: list[object],
        catalog_by_brand: dict[str, list[object]],
        catalog_identifier_fields: list[str],
        locked_mappings: list[object],
        auto_threshold: int,
        review_threshold: int,
        disable_fuzzy: bool,
    ) -> MatchResult | None:
        if not item.brand or not item.affiliate_url:
            return None
        return self.matching_service._match_item(  # noqa: SLF001
            item,
            catalog_rows=catalog_rows,
            catalog_by_brand=catalog_by_brand,
            catalog_identifier_fields=catalog_identifier_fields,
            locked_mappings=locked_mappings,
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
            disable_fuzzy=disable_fuzzy,
        )

    def _build_candidate_decision(
        self,
        *,
        item: LoadedNormalizedItem,
        status: str,
        match_result: MatchResult | None,
        source_classification: str,
        explicit_match_reason: str | None = None,
    ) -> CandidateDecision:
        score = None
        proposed_perfume_id = None
        match_status_from_pr07 = "unmatched"
        match_method = "none"
        match_components: dict[str, object] = {}
        match_reason = explicit_match_reason or ""

        if match_result is not None:
            proposed_perfume_id = match_result.perfume_id
            match_status_from_pr07 = match_result.status
            match_method = match_result.method
            match_components = match_result.match_components
            if match_result.score > 0:
                score = Decimal(str(match_result.score))
            if not match_reason:
                match_reason = match_result.match_reason

        if not match_reason:
            if status == "pending":
                match_reason = "No confident catalog match found."
            elif status == "needs_review":
                match_reason = "Candidate requires manual review."
            elif status == "rejected_not_perfume":
                match_reason = "Excluded non-perfume row."
            else:
                match_reason = "Candidate ignored by automated rules."

        return CandidateDecision(
            item=item,
            dedupe_key=build_candidate_dedupe_key(item),
            status=status,
            proposed_perfume_id=proposed_perfume_id,
            match_score=score,
            match_reason=match_reason,
            source_classification=source_classification,
            match_status_from_pr07=match_status_from_pr07,
            match_method=match_method,
            match_components=match_components,
        )

    def _aggregate_decisions(
        self,
        decisions: list[CandidateDecision],
    ) -> list[CandidateAggregate]:
        grouped: dict[str, list[CandidateDecision]] = {}
        for decision in decisions:
            grouped.setdefault(decision.dedupe_key, []).append(decision)

        aggregates: list[CandidateAggregate] = []
        for dedupe_key, group in grouped.items():
            primary = sorted(
                group,
                key=lambda entry: (
                    self._status_priority(entry.status),
                    float(entry.match_score or Decimal("0")),
                    -entry.item.raw_feed_item_id,
                ),
                reverse=True,
            )[0]
            aggregates.append(
                CandidateAggregate(
                    dedupe_key=dedupe_key,
                    primary=primary,
                    source_count=len(group),
                )
            )
        aggregates.sort(key=lambda aggregate: aggregate.primary.item.raw_feed_item_id)
        return aggregates

    def _status_priority(self, status: str) -> int:
        priorities = {
            "needs_review": 4,
            "pending": 3,
            "rejected_not_perfume": 2,
            "ignored": 1,
        }
        return priorities.get(status, 0)

    def _status_counts(self, aggregates: list[CandidateAggregate]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for aggregate in aggregates:
            counts[aggregate.primary.status] = counts.get(aggregate.primary.status, 0) + 1
        return counts

    def _load_existing_candidate(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        dedupe_key: str,
    ) -> dict[str, object] | None:
        row = conn.execute(
            """
            select *
            from product_match_candidates
            where advertiser_id = %s
              and dedupe_key = %s
            """,
            (advertiser_db_id, dedupe_key),
        ).fetchone()
        return dict(row) if row is not None else None

    def _persist_candidates(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        aggregates: list[CandidateAggregate],
        network_feed_id: str,
    ) -> tuple[
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, object]],
    ]:
        created = 0
        updated = 0
        unchanged = 0
        ignored_existing_status = 0
        rejected_not_perfume = 0
        pending_count = 0
        needs_review_count = 0
        sample_created: list[dict[str, object]] = []
        sample_updated: list[dict[str, object]] = []
        sample_ignored: list[dict[str, object]] = []

        with conn.transaction():
            for aggregate in aggregates:
                decision = aggregate.primary
                if decision.status == "rejected_not_perfume":
                    rejected_not_perfume += 1
                elif decision.status == "pending":
                    pending_count += 1
                elif decision.status == "needs_review":
                    needs_review_count += 1

                existing_candidate = self._load_existing_candidate(
                    conn,
                    advertiser_db_id=advertiser_db_id,
                    dedupe_key=aggregate.dedupe_key,
                )
                if (
                    existing_candidate is not None
                    and existing_candidate["status"] in MANUAL_FINAL_CANDIDATE_STATUSES
                ):
                    ignored_existing_status += 1
                    if len(sample_ignored) < 5:
                        sample_ignored.append(
                            self._sample_existing_candidate(existing_candidate)
                        )
                    continue

                enrichment_payload = self._build_enrichment_payload(
                    decision,
                    source_count=aggregate.source_count,
                    network_feed_id=network_feed_id,
                )
                candidate_url = decision.item.affiliate_url or decision.item.merchant_url
                existing_payload = (
                    dict(existing_candidate["enrichment_payload"])
                    if existing_candidate is not None
                    else None
                )

                if existing_candidate is None:
                    conn.execute(
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
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        """,
                        (
                            advertiser_db_id,
                            decision.item.raw_feed_item_id,
                            decision.item.brand,
                            decision.item.title,
                            decision.item.concentration,
                            decision.item.volume_ml,
                            decision.item.category or decision.item.normalized_category,
                            decision.item.image_url,
                            candidate_url,
                            decision.proposed_perfume_id,
                            decision.match_score,
                            decision.match_reason,
                            decision.status,
                            aggregate.source_count,
                            1,
                            Jsonb(enrichment_payload),
                            aggregate.dedupe_key,
                        ),
                    )
                    created += 1
                    if len(sample_created) < 5:
                        sample_created.append(
                            self._sample_candidate(decision, aggregate.source_count)
                        )
                    continue

                changed = any(
                    [
                        existing_candidate["raw_feed_item_id"] != decision.item.raw_feed_item_id,
                        existing_candidate["candidate_brand"] != decision.item.brand,
                        existing_candidate["candidate_name"] != decision.item.title,
                        existing_candidate["candidate_concentration"]
                        != decision.item.concentration,
                        existing_candidate["candidate_volume_ml"] != decision.item.volume_ml,
                        existing_candidate["candidate_category"]
                        != (decision.item.category or decision.item.normalized_category),
                        existing_candidate["candidate_image_url"] != decision.item.image_url,
                        existing_candidate["candidate_url"] != candidate_url,
                        (
                            str(existing_candidate["proposed_perfume_id"])
                            if existing_candidate["proposed_perfume_id"] is not None
                            else None
                        )
                        != decision.proposed_perfume_id,
                        existing_candidate["match_score"] != decision.match_score,
                        existing_candidate["match_reason"] != decision.match_reason,
                        existing_candidate["status"] != decision.status,
                        int(existing_candidate["source_count"] or 0) != aggregate.source_count,
                        int(existing_candidate["advertiser_count"] or 1) != 1,
                        existing_payload != enrichment_payload,
                    ]
                )
                if not changed:
                    unchanged += 1
                    continue

                conn.execute(
                    """
                    update product_match_candidates
                    set raw_feed_item_id = %s,
                        candidate_brand = %s,
                        candidate_name = %s,
                        candidate_concentration = %s,
                        candidate_volume_ml = %s,
                        candidate_category = %s,
                        candidate_image_url = %s,
                        candidate_url = %s,
                        proposed_perfume_id = %s,
                        match_score = %s,
                        match_reason = %s,
                        status = %s,
                        source_count = %s,
                        advertiser_count = %s,
                        enrichment_payload = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        decision.item.raw_feed_item_id,
                        decision.item.brand,
                        decision.item.title,
                        decision.item.concentration,
                        decision.item.volume_ml,
                        decision.item.category or decision.item.normalized_category,
                        decision.item.image_url,
                        candidate_url,
                        decision.proposed_perfume_id,
                        decision.match_score,
                        decision.match_reason,
                        decision.status,
                        aggregate.source_count,
                        1,
                        Jsonb(enrichment_payload),
                        existing_candidate["id"],
                    ),
                )
                updated += 1
                if len(sample_updated) < 5:
                    sample_updated.append(
                        self._sample_candidate(decision, aggregate.source_count)
                    )

        return (
            created,
            updated,
            unchanged,
            ignored_existing_status,
            rejected_not_perfume,
            pending_count,
            needs_review_count,
            sample_created,
            sample_updated,
            sample_ignored,
        )

    def _build_enrichment_payload(
        self,
        decision: CandidateDecision,
        *,
        source_count: int,
        network_feed_id: str,
    ) -> dict[str, object]:
        item = decision.item
        return {
            "network": item.network,
            "network_feed_id": network_feed_id,
            "normalized_feed_item_id": item.id,
            "raw_feed_item_id": item.raw_feed_item_id,
            "network_product_id": item.network_product_id,
            "merchant_product_id": item.merchant_product_id,
            "title": item.title,
            "normalized_title": item.normalized_title,
            "brand": item.brand,
            "normalized_brand": item.normalized_brand,
            "price": _decimal_to_string(item.price),
            "currency": item.currency,
            "affiliate_url": item.affiliate_url,
            "merchant_url": item.merchant_url,
            "image_url": item.image_url,
            "ean": item.ean,
            "gtin": item.gtin,
            "upc": item.upc,
            "mpn": item.mpn,
            "concentration": item.concentration,
            "volume_ml": _decimal_to_string(item.volume_ml),
            "is_excluded": item.is_excluded,
            "exclusion_reasons": item.exclusion_reasons,
            "match_status_from_pr07": decision.match_status_from_pr07,
            "match_method": decision.match_method,
            "match_components": decision.match_components,
            "source": "pr08",
            "source_count": source_count,
            "dedupe_key": decision.dedupe_key,
        }

    def _sample_candidate(
        self,
        decision: CandidateDecision,
        source_count: int,
    ) -> dict[str, object]:
        return {
            "raw_feed_item_id": decision.item.raw_feed_item_id,
            "candidate_name": decision.item.title,
            "candidate_brand": decision.item.brand,
            "status": decision.status,
            "proposed_perfume_id": decision.proposed_perfume_id,
            "match_score": (
                float(decision.match_score)
                if decision.match_score is not None
                else None
            ),
            "match_reason": decision.match_reason,
            "source_count": source_count,
        }

    def _sample_existing_candidate(
        self,
        existing_candidate: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "candidate_id": existing_candidate["id"],
            "candidate_name": existing_candidate["candidate_name"],
            "status": existing_candidate["status"],
            "match_reason": existing_candidate["match_reason"],
        }

    def _load_candidate_status_counts(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
    ) -> dict[str, int]:
        rows = conn.execute(
            """
            select status, count(*)::integer as candidate_count
            from product_match_candidates
            where advertiser_id = %s
            group by status
            order by status
            """,
            (advertiser_db_id,),
        ).fetchall()
        return {str(row["status"]): int(row["candidate_count"]) for row in rows}


def format_candidate_report_summary(report: Mapping[str, object], report_path: Path) -> str:
    lines = [
        f"status={report.get('status')}",
        f"dry_run={report.get('dry_run')}",
        f"normalized_rows_total={report.get('normalized_rows_total')}",
        f"rows_needs_review_from_matching={report.get('rows_needs_review_from_matching')}",
        f"rows_unmatched_from_matching={report.get('rows_unmatched_from_matching')}",
        f"rows_excluded_considered={report.get('rows_excluded_considered')}",
        f"candidates_created={report.get('candidates_created')}",
        f"candidates_updated={report.get('candidates_updated')}",
        f"candidates_unchanged={report.get('candidates_unchanged')}",
        f"candidates_ignored_existing_status={report.get('candidates_ignored_existing_status')}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)


def format_insert_candidate_sync_summary(
    report: Mapping[str, object],
    report_path: Path,
) -> str:
    lines = [
        f"status={report.get('status')}",
        f"dry_run={report.get('dry_run')}",
        f"candidates_analyzed={report.get('candidates_analyzed')}",
        f"staging_inserted={report.get('staging_inserted')}",
        f"staging_updated={report.get('staging_updated')}",
        f"staging_ignored_manual_status={report.get('staging_ignored_manual_status')}",
        f"safe_new_candidates_count={report.get('safe_new_candidates_count')}",
        f"markdown_report_path={report.get('markdown_report_path')}",
        f"safe_csv_path={report.get('safe_csv_path')}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)


def format_refresh_candidate_summary(
    report: Mapping[str, object],
    report_path: Path,
) -> str:
    lines = [
        f"status={report.get('status')}",
        f"dry_run={report.get('dry_run')}",
        f"candidates_loaded={report.get('candidates_loaded')}",
        f"candidates_updated={report.get('candidates_updated')}",
        f"candidates_without_match={report.get('candidates_without_match')}",
        f"candidates_unchanged={report.get('candidates_unchanged')}",
        f"candidates_ignored_closed_status={report.get('candidates_ignored_closed_status')}",
        f"markdown_report_path={report.get('markdown_report_path')}",
        f"csv_report_path={report.get('csv_report_path')}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)
