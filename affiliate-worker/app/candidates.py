from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from app.config import Settings
from app.db import DatabaseService
from app.matching import (
    LoadedNormalizedItem,
    MatchingService,
    MatchResult,
    build_perfume_match_key,
)
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


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
