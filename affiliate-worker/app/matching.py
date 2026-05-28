from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from app.config import Settings
from app.db import DatabaseService, DbCommandError
from app.normalization import calculate_coverage_percent, normalize_text
from app.reporting import try_write_report, write_report

AUTO_MATCH_STATUSES = {
    "matched_exact_identifier",
    "matched_locked_mapping",
    "matched_deterministic_key",
    "matched_fuzzy",
}
EXACT_IDENTIFIER_FIELDS = ("ean", "gtin", "upc", "mpn")
CONCENTRATION_STRIP_PATTERNS = {
    "edp": (r"\beau de parfum\b", r"\bedp\b"),
    "edt": (r"\beau de toilette\b", r"\bedt\b"),
    "edc": (r"\beau de cologne\b", r"\bedc\b"),
    "parfum": (r"\bparfum\b",),
    "extrait": (r"\bextrait de parfum\b", r"\bextrait\b"),
    "eau_fraiche": (r"\beau fraiche\b", r"\beau fraiche\b"),
}
NAME_NOISE_PATTERNS = (
    r"\bnatural spray\b",
    r"\bvaporisateur\b",
    r"\bspray\b",
    r"\bfor women\b",
    r"\bfor men\b",
)
VOLUME_PATTERNS = (
    r"\b\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?\s*(?:ml|cl|l|oz)\b",
    r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|l|oz)\s*x\s*\d+(?:[.,]\d+)?\b",
    r"\b\d+(?:[.,]\d+)?\s*\+\s*\d+(?:[.,]\d+)?\s*(?:ml|cl|l|oz)\b",
    r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|l|oz)\b",
)


class MatchingError(RuntimeError):
    """Raised when affiliate offer matching cannot complete safely."""


@dataclass(frozen=True)
class CatalogPerfume:
    id: str
    name: str
    slug: str | None
    brand: str
    normalized_brand: str
    match_key: str
    slug_key: str
    concentration: str | None
    volume_ml: Decimal | None
    identifiers: dict[str, str]


@dataclass(frozen=True)
class LockedMapping:
    perfume_id: str
    network_product_id: str | None
    merchant_product_id: str | None
    confidence: float


@dataclass(frozen=True)
class MatchResult:
    status: str
    score: float
    method: str
    perfume_id: str | None
    perfume_name: str | None
    match_reason: str
    match_components: dict[str, object]

    @property
    def is_auto_match(self) -> bool:
        return self.status in AUTO_MATCH_STATUSES


@dataclass(frozen=True)
class LoadedNormalizedItem:
    id: int
    raw_feed_item_id: int
    raw_hash: str
    import_run_id: int
    advertiser_id: int
    feed_id: int
    network: str
    network_product_id: str | None
    merchant_product_id: str | None
    title: str
    normalized_title: str
    description: str | None
    brand: str | None
    normalized_brand: str | None
    category: str | None
    normalized_category: str | None
    price: Decimal | None
    currency: str | None
    delivery_cost: Decimal | None
    affiliate_url: str | None
    merchant_url: str | None
    image_url: str | None
    ean: str | None
    gtin: str | None
    upc: str | None
    mpn: str | None
    in_stock: bool | None
    stock_status: str | None
    concentration: str | None
    volume_ml: Decimal | None
    is_fragrance: bool
    is_excluded: bool
    exclusion_reasons: list[str]
    missing_required_columns: list[str]
    missing_recommended_columns: list[str]
    normalized_payload: dict[str, object]
    raw_payload: dict[str, object]
    match_key: str


@dataclass(frozen=True)
class OfferUpsertPlan:
    action: str
    price_changed: bool
    merged_metadata: dict[str, object]
    changed_fields: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def brand_compatible(feed_brand: str | None, catalog_brand: str | None) -> bool:
    normalized_feed_brand = normalize_text(feed_brand)
    normalized_catalog_brand = normalize_text(catalog_brand)
    if not normalized_feed_brand or not normalized_catalog_brand:
        return False
    return normalized_feed_brand == normalized_catalog_brand


def build_perfume_match_key(
    value: str | None,
    *,
    brand: str | None = None,
    concentration: str | None = None,
    volume_ml: Decimal | None = None,
) -> str:
    text = normalize_text(value)
    if not text:
        return ""

    normalized_brand = normalize_text(brand)
    if normalized_brand:
        text = re.sub(rf"\b{re.escape(normalized_brand)}\b", " ", text)

    if concentration:
        for pattern in CONCENTRATION_STRIP_PATTERNS.get(concentration, ()):
            text = re.sub(pattern, " ", text)

    for pattern in VOLUME_PATTERNS:
        text = re.sub(pattern, " ", text)

    if volume_ml is not None:
        volume_text = format(volume_ml.normalize(), "f").rstrip("0").rstrip(".")
        if volume_text:
            text = re.sub(rf"\b{re.escape(volume_text)}\b", " ", text)

    for pattern in NAME_NOISE_PATTERNS:
        text = re.sub(pattern, " ", text)

    text = re.sub(r"\b(?:ml|cl|l|oz)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def token_set_score(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0

    common = sorted(left_tokens & right_tokens)
    left_unique = sorted(left_tokens - right_tokens)
    right_unique = sorted(right_tokens - left_tokens)
    normalized_left = " ".join([*common, *left_unique]).strip()
    normalized_right = " ".join([*common, *right_unique]).strip()
    return round(
        difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio() * 100,
        2,
    )


def fuzzy_name_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    sequence_score = difflib.SequenceMatcher(None, left, right).ratio() * 100
    return round(max(sequence_score, token_set_score(left, right)), 2)


class MatchingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_service = DatabaseService(settings)

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
        self.db_service.require_database_url()

        auto_threshold = int(min_score or self.settings.affiliate_match_auto_threshold)
        review_threshold = int(self.settings.affiliate_match_review_threshold)
        deactivate_after = int(self.settings.affiliate_deactivate_after_missed_imports)

        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "match-offers",
            "network": "awin",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "dry_run": dry_run,
            "source": "normalized_feed_items",
            "database_url_redacted": True,
            "selection_limit": limit,
            "auto_threshold": auto_threshold,
            "review_threshold": review_threshold,
            "deactivate_after_missed_imports": deactivate_after,
            "match_method_counts": {},
            "status_counts": {},
            "sample_matches": [],
            "sample_needs_review": [],
            "sample_unmatched": [],
            "warnings": [],
        }

        try:
            with self.db_service.connect() as conn:
                advertiser_row, affiliate_feed_row = self._resolve_feed_context(
                    conn,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )
                import_run_id = self._select_source_import_run(
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                )
                normalized_items = self._load_normalized_rows(
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                    import_run_id=import_run_id,
                    limit=limit,
                )
                if not normalized_items:
                    raise MatchingError(
                        "No normalized_feed_items found for the latest successful import run."
                    )

                catalog_rows, available_catalog_columns = self._load_catalog_perfumes(conn)
                locked_mappings = self._load_locked_mappings(
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    auto_threshold=auto_threshold,
                )
                catalog_identifier_fields = [
                    field for field in EXACT_IDENTIFIER_FIELDS if field in available_catalog_columns
                ]
                exact_identifier_enabled = bool(catalog_identifier_fields)
                if not exact_identifier_enabled:
                    report["warnings"].append(
                        "Exact identifier matching disabled: perfumes has no compatible "
                        "EAN/GTIN/UPC/MPN fields."
                    )
                if disable_fuzzy:
                    report["warnings"].append("Fuzzy matching disabled by CLI flag.")

                catalog_by_brand: dict[str, list[CatalogPerfume]] = {}
                for perfume in catalog_rows:
                    catalog_by_brand.setdefault(perfume.normalized_brand, []).append(perfume)

                offers_inserted = 0
                offers_updated = 0
                offers_unchanged = 0
                offers_price_changed = 0
                offers_seen = 0
                stale_offers_incremented = 0
                stale_offers_deactivated = 0
                rows_actionable_input = 0
                rows_skipped_non_fragrance = 0
                rows_skipped_excluded = 0
                rows_skipped_missing_required = 0
                rows_matched_exact_identifier = 0
                rows_matched_locked_mapping = 0
                rows_matched_deterministic_key = 0
                rows_matched_fuzzy = 0
                rows_needs_review = 0
                rows_unmatched = 0
                seen_offer_keys: set[tuple[str | None, str | None]] = set()

                for item in normalized_items:
                    if not item.is_fragrance:
                        rows_skipped_non_fragrance += 1
                        self._increment_counter(report["status_counts"], "non_fragrance")
                        continue
                    if item.is_excluded:
                        rows_skipped_excluded += 1
                        self._increment_counter(report["status_counts"], "excluded")
                        continue

                    missing_required = self._missing_required_fields(item)
                    if missing_required:
                        rows_skipped_missing_required += 1
                        self._increment_counter(report["status_counts"], "missing_required")
                        if len(report["warnings"]) < 10:
                            report["warnings"].append(
                                f"Skipped raw_feed_item_id={item.raw_feed_item_id}: "
                                f"missing {', '.join(missing_required)}."
                            )
                        continue

                    rows_actionable_input += 1
                    seen_offer_keys.add((item.network_product_id, item.merchant_product_id))
                    match_result = self._match_item(
                        item,
                        catalog_rows=catalog_rows,
                        catalog_by_brand=catalog_by_brand,
                        catalog_identifier_fields=catalog_identifier_fields,
                        locked_mappings=locked_mappings,
                        auto_threshold=auto_threshold,
                        review_threshold=review_threshold,
                        disable_fuzzy=disable_fuzzy,
                    )

                    self._increment_counter(report["status_counts"], match_result.status)
                    self._increment_counter(report["match_method_counts"], match_result.method)

                    if match_result.status == "matched_exact_identifier":
                        rows_matched_exact_identifier += 1
                    elif match_result.status == "matched_locked_mapping":
                        rows_matched_locked_mapping += 1
                    elif match_result.status == "matched_deterministic_key":
                        rows_matched_deterministic_key += 1
                    elif match_result.status == "matched_fuzzy":
                        rows_matched_fuzzy += 1
                    elif match_result.status == "needs_review":
                        rows_needs_review += 1
                    elif match_result.status == "unmatched":
                        rows_unmatched += 1

                    self._append_sample(
                        report,
                        item=item,
                        match_result=match_result,
                    )

                    if not match_result.is_auto_match or match_result.score < auto_threshold:
                        continue

                    offers_seen += 1
                    if dry_run:
                        continue

                    offer_action, price_changed = self._upsert_offer(
                        conn,
                        item=item,
                        advertiser_db_id=int(advertiser_row["id"]),
                        network_feed_id=str(affiliate_feed_row["network_feed_id"]),
                        match_result=match_result,
                    )
                    if offer_action == "inserted":
                        offers_inserted += 1
                    elif offer_action == "updated":
                        offers_updated += 1
                    else:
                        offers_unchanged += 1
                    if price_changed:
                        offers_price_changed += 1

                rows_matched_total = (
                    rows_matched_exact_identifier
                    + rows_matched_locked_mapping
                    + rows_matched_deterministic_key
                    + rows_matched_fuzzy
                )

                if not dry_run and not no_stale_update:
                    stale_offers_incremented, stale_offers_deactivated = self._update_stale_offers(
                        conn,
                        advertiser_db_id=int(advertiser_row["id"]),
                        network_feed_id=str(affiliate_feed_row["network_feed_id"]),
                        seen_offer_keys=seen_offer_keys,
                        deactivate_after=deactivate_after,
                    )
                elif no_stale_update:
                    report["warnings"].append("Stale offer update disabled by CLI flag.")

                report.update(
                    {
                        "status": "success",
                        "import_run_id": import_run_id,
                        "advertiser_db_id": advertiser_row["id"],
                        "affiliate_feed_db_id": affiliate_feed_row["id"],
                        "normalized_rows_total": len(normalized_items),
                        "rows_actionable_input": rows_actionable_input,
                        "rows_skipped_non_fragrance": rows_skipped_non_fragrance,
                        "rows_skipped_excluded": rows_skipped_excluded,
                        "rows_skipped_missing_required": rows_skipped_missing_required,
                        "rows_matched_total": rows_matched_total,
                        "rows_matched_exact_identifier": rows_matched_exact_identifier,
                        "rows_matched_locked_mapping": rows_matched_locked_mapping,
                        "rows_matched_deterministic_key": rows_matched_deterministic_key,
                        "rows_matched_fuzzy": rows_matched_fuzzy,
                        "rows_needs_review": rows_needs_review,
                        "rows_unmatched": rows_unmatched,
                        "offers_inserted": offers_inserted,
                        "offers_updated": offers_updated,
                        "offers_unchanged": offers_unchanged,
                        "offers_price_changed": offers_price_changed,
                        "offers_seen": offers_seen,
                        "stale_offers_incremented": stale_offers_incremented,
                        "stale_offers_deactivated": stale_offers_deactivated,
                        "catalog_perfumes_total": len(catalog_rows),
                        "catalog_identifier_fields_available": bool(catalog_identifier_fields),
                        "exact_identifier_matching_enabled": exact_identifier_enabled,
                        "brand_coverage_percent": calculate_coverage_percent(
                            sum(1 for item in normalized_items if item.brand),
                            len(normalized_items),
                        ),
                        "sample_matches": report["sample_matches"],
                        "sample_needs_review": report["sample_needs_review"],
                        "sample_unmatched": report["sample_unmatched"],
                    }
                )
                report_path = write_report(
                    self.settings.affiliate_data_dir,
                    "match_offers",
                    report,
                )
                return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "match_offers_error",
                report,
            )
            if report_path is not None:
                raise MatchingError(f"{message}. Report written to {report_path}") from exc
            raise MatchingError(message) from exc

    def _resolve_feed_context(
        self,
        conn: Any,
        *,
        advertiser_id: str,
        feed_id: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        advertiser_row = conn.execute(
            """
            select id, network, network_advertiser_id
            from advertisers
            where network = 'awin'
              and network_advertiser_id = %s
            """,
            (advertiser_id,),
        ).fetchone()
        if advertiser_row is None:
            raise DbCommandError(
                "Missing advertiser seed for network=awin "
                f"network_advertiser_id={advertiser_id}. "
                "Run migrate-db from PR04 first."
            )

        affiliate_feed_row = conn.execute(
            """
            select id, advertiser_id, network_feed_id
            from affiliate_feeds
            where network = 'awin'
              and network_feed_id = %s
            """,
            (feed_id,),
        ).fetchone()
        if affiliate_feed_row is None:
            raise DbCommandError(
                "Missing affiliate feed seed for network=awin "
                f"network_feed_id={feed_id}. "
                "Run migrate-db from PR04 first."
            )
        if int(affiliate_feed_row["advertiser_id"]) != int(advertiser_row["id"]):
            raise DbCommandError(
                f"Affiliate feed {feed_id} is not linked to advertiser {advertiser_id}."
            )

        return dict(advertiser_row), dict(affiliate_feed_row)

    def _select_source_import_run(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        affiliate_feed_db_id: int,
    ) -> int:
        row = conn.execute(
            """
            select fir.id
            from feed_import_runs fir
            join raw_feed_items rfi
              on rfi.import_run_id = fir.id
             and rfi.advertiser_id = %s
            join normalized_feed_items nfi
              on nfi.raw_feed_item_id = rfi.id
             and nfi.advertiser_id = %s
             and nfi.feed_id = %s
            where fir.feed_id = %s
              and fir.status = 'success'
            group by fir.id
            order by fir.id desc
            limit 1
            """,
            (
                advertiser_db_id,
                advertiser_db_id,
                affiliate_feed_db_id,
                affiliate_feed_db_id,
            ),
        ).fetchone()
        if row is None:
            raise MatchingError(
                "No successful normalized feed import with persisted rows was found for this feed."
            )
        return int(row["id"])

    def _load_normalized_rows(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        affiliate_feed_db_id: int,
        import_run_id: int,
        limit: int | None,
    ) -> list[LoadedNormalizedItem]:
        sql = """
            select
                nfi.*,
                rfi.import_run_id,
                rfi.raw_hash,
                rfi.raw_payload
            from normalized_feed_items nfi
            join raw_feed_items rfi
              on rfi.id = nfi.raw_feed_item_id
            where nfi.advertiser_id = %s
              and nfi.feed_id = %s
              and rfi.import_run_id = %s
            order by nfi.id
        """
        params: list[object] = [advertiser_db_id, affiliate_feed_db_id, import_run_id]
        if limit is not None:
            sql += " limit %s"
            params.append(limit)

        rows = conn.execute(sql, tuple(params)).fetchall()
        loaded_items: list[LoadedNormalizedItem] = []
        for row in rows:
            payload = dict(row["normalized_payload"])
            loaded_items.append(
                LoadedNormalizedItem(
                    id=int(row["id"]),
                    raw_feed_item_id=int(row["raw_feed_item_id"]),
                    raw_hash=str(row["raw_hash"]),
                    import_run_id=int(row["import_run_id"]),
                    advertiser_id=int(row["advertiser_id"]),
                    feed_id=int(row["feed_id"]),
                    network=str(row["network"]),
                    network_product_id=row["network_product_id"],
                    merchant_product_id=row["merchant_product_id"],
                    title=str(row["title"]),
                    normalized_title=str(row["normalized_title"]),
                    description=row["description"],
                    brand=row["brand"],
                    normalized_brand=row["normalized_brand"],
                    category=row["category"],
                    normalized_category=row["normalized_category"],
                    price=row["price"],
                    currency=row["currency"],
                    delivery_cost=row["delivery_cost"],
                    affiliate_url=row["affiliate_url"],
                    merchant_url=row["merchant_url"],
                    image_url=row["image_url"],
                    ean=row["ean"],
                    gtin=row["gtin"],
                    upc=row["upc"],
                    mpn=row["mpn"],
                    in_stock=row["in_stock"],
                    stock_status=row["stock_status"],
                    concentration=row["concentration"],
                    volume_ml=row["volume_ml"],
                    is_fragrance=bool(row["is_fragrance"]),
                    is_excluded=bool(row["is_excluded"]),
                    exclusion_reasons=list(row["exclusion_reasons"]),
                    missing_required_columns=list(row["missing_required_columns"]),
                    missing_recommended_columns=list(row["missing_recommended_columns"]),
                    normalized_payload=payload,
                    raw_payload=dict(row["raw_payload"]),
                    match_key=build_perfume_match_key(
                        payload.get("title"),
                        brand=row["brand"],
                        concentration=row["concentration"],
                        volume_ml=row["volume_ml"],
                    ),
                )
            )
        return loaded_items

    def _load_catalog_perfumes(
        self,
        conn: Any,
    ) -> tuple[list[CatalogPerfume], set[str]]:
        column_rows = conn.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'perfumes'
            order by column_name
            """
        ).fetchall()
        available_columns = {str(row["column_name"]) for row in column_rows}
        rows = conn.execute("select * from perfumes order by brand, name, id").fetchall()

        catalog_rows: list[CatalogPerfume] = []
        for row in rows:
            brand = str(row["brand"])
            name = str(row["name"])
            concentration = (
                str(row["concentration"])
                if "concentration" in available_columns and row.get("concentration") is not None
                else None
            )
            volume_ml = (
                row["volume_ml"]
                if "volume_ml" in available_columns and row.get("volume_ml") is not None
                else None
            )
            identifiers = {
                field: str(row[field]).strip()
                for field in EXACT_IDENTIFIER_FIELDS
                if (
                    field in available_columns
                    and row.get(field) is not None
                    and str(row[field]).strip()
                )
            }
            catalog_rows.append(
                CatalogPerfume(
                    id=str(row["id"]),
                    name=name,
                    slug=str(row["slug"]) if row.get("slug") is not None else None,
                    brand=brand,
                    normalized_brand=normalize_text(brand),
                    match_key=build_perfume_match_key(
                        name,
                        brand=brand,
                        concentration=concentration,
                        volume_ml=volume_ml,
                    ),
                    slug_key=normalize_text(str(row["slug"])) if row.get("slug") else "",
                    concentration=concentration,
                    volume_ml=volume_ml,
                    identifiers=identifiers,
                )
            )
        return catalog_rows, available_columns

    def _load_locked_mappings(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        auto_threshold: int,
    ) -> list[LockedMapping]:
        rows = conn.execute(
            """
            select perfume_id, network_product_id, merchant_product_id, confidence
            from external_product_mappings
            where advertiser_id = %s
              and locked = true
              and confidence >= %s
            order by id
            """,
            (advertiser_db_id, auto_threshold),
        ).fetchall()
        return [
            LockedMapping(
                perfume_id=str(row["perfume_id"]),
                network_product_id=row["network_product_id"],
                merchant_product_id=row["merchant_product_id"],
                confidence=float(row["confidence"]),
            )
            for row in rows
        ]

    def _match_item(
        self,
        item: LoadedNormalizedItem,
        *,
        catalog_rows: list[CatalogPerfume],
        catalog_by_brand: dict[str, list[CatalogPerfume]],
        catalog_identifier_fields: list[str],
        locked_mappings: list[LockedMapping],
        auto_threshold: int,
        review_threshold: int,
        disable_fuzzy: bool,
    ) -> MatchResult:
        locked_result = self._match_locked_mapping(
            item,
            catalog_rows=catalog_rows,
            locked_mappings=locked_mappings,
        )
        if locked_result is not None:
            return locked_result

        exact_result = self._match_exact_identifier(
            item,
            catalog_rows=catalog_rows,
            catalog_identifier_fields=catalog_identifier_fields,
        )
        if exact_result is not None:
            return exact_result

        brand_candidates = catalog_by_brand.get(item.normalized_brand or "", [])
        if not brand_candidates:
            return MatchResult(
                status="unmatched",
                score=0.0,
                method="none",
                perfume_id=None,
                perfume_name=None,
                match_reason="No catalog perfume with a compatible brand was found.",
                match_components={"brand_score": 0, "name_score": 0},
            )

        deterministic = self._match_deterministic_key(item, brand_candidates)
        if deterministic is not None:
            return deterministic

        if disable_fuzzy:
            return MatchResult(
                status="unmatched",
                score=0.0,
                method="none",
                perfume_id=None,
                perfume_name=None,
                match_reason="No deterministic match and fuzzy matching is disabled.",
                match_components={"brand_score": 100, "name_score": 0},
            )

        return self._match_fuzzy(
            item,
            brand_candidates=brand_candidates,
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
        )

    def _match_locked_mapping(
        self,
        item: LoadedNormalizedItem,
        *,
        catalog_rows: list[CatalogPerfume],
        locked_mappings: list[LockedMapping],
    ) -> MatchResult | None:
        candidates: list[LockedMapping] = []
        for mapping in locked_mappings:
            if (
                item.network_product_id
                and mapping.network_product_id
                and mapping.network_product_id == item.network_product_id
            ) or (
                item.merchant_product_id
                and mapping.merchant_product_id
                and mapping.merchant_product_id == item.merchant_product_id
            ):
                candidates.append(mapping)

        if not candidates:
            return None

        unique_perfume_ids = {candidate.perfume_id for candidate in candidates}
        if len(unique_perfume_ids) != 1:
            return MatchResult(
                status="needs_review",
                score=0.0,
                method="locked_mapping",
                perfume_id=None,
                perfume_name=None,
                match_reason="Multiple locked mappings matched this row.",
                match_components={"brand_score": 0, "name_score": 0},
            )

        perfume = next(
            (catalog_row for catalog_row in catalog_rows if catalog_row.id in unique_perfume_ids),
            None,
        )
        if perfume is None:
            return MatchResult(
                status="needs_review",
                score=0.0,
                method="locked_mapping",
                perfume_id=None,
                perfume_name=None,
                match_reason="Locked mapping points to a missing catalog perfume.",
                match_components={"brand_score": 0, "name_score": 0},
            )

        if not brand_compatible(item.brand, perfume.brand):
            return MatchResult(
                status="needs_review",
                score=0.0,
                method="locked_mapping",
                perfume_id=perfume.id,
                perfume_name=perfume.name,
                match_reason="Locked mapping matched but brand is incompatible.",
                match_components={"brand_score": 0, "name_score": 0},
            )

        return MatchResult(
            status="matched_locked_mapping",
            score=100.0,
            method="locked_mapping",
            perfume_id=perfume.id,
            perfume_name=perfume.name,
            match_reason="Matched by locked external mapping.",
            match_components={"brand_score": 100, "name_score": 100},
        )

    def _match_exact_identifier(
        self,
        item: LoadedNormalizedItem,
        *,
        catalog_rows: list[CatalogPerfume],
        catalog_identifier_fields: list[str],
    ) -> MatchResult | None:
        if not catalog_identifier_fields:
            return None

        matches_by_identifier: dict[str, list[CatalogPerfume]] = {}
        for field in catalog_identifier_fields:
            value = getattr(item, field)
            if not value:
                continue
            matches = [
                perfume for perfume in catalog_rows if perfume.identifiers.get(field) == value
            ]
            if matches:
                matches_by_identifier[field] = matches

        if not matches_by_identifier:
            return None

        unique_perfume_ids = {
            perfume.id
            for matches in matches_by_identifier.values()
            for perfume in matches
        }
        if len(unique_perfume_ids) != 1:
            return MatchResult(
                status="needs_review",
                score=0.0,
                method="exact_identifier",
                perfume_id=None,
                perfume_name=None,
                match_reason="Identifier match is ambiguous across multiple perfumes.",
                match_components={
                    "identifier_fields": sorted(matches_by_identifier),
                    "brand_score": 0,
                    "name_score": 0,
                },
            )

        perfume = next(
            perfume for perfume in catalog_rows if perfume.id == next(iter(unique_perfume_ids))
        )
        if not brand_compatible(item.brand, perfume.brand):
            return MatchResult(
                status="needs_review",
                score=0.0,
                method="exact_identifier",
                perfume_id=perfume.id,
                perfume_name=perfume.name,
                match_reason="Identifier matched but brand is incompatible.",
                match_components={
                    "identifier_fields": sorted(matches_by_identifier),
                    "brand_score": 0,
                    "name_score": 0,
                },
            )

        matched_field = sorted(matches_by_identifier)[0]
        return MatchResult(
            status="matched_exact_identifier",
            score=100.0,
            method="exact_identifier",
            perfume_id=perfume.id,
            perfume_name=perfume.name,
            match_reason=f"Matched by exact {matched_field}.",
            match_components={
                "identifier_fields": sorted(matches_by_identifier),
                "brand_score": 100,
                "name_score": 100,
            },
        )

    def _match_deterministic_key(
        self,
        item: LoadedNormalizedItem,
        brand_candidates: list[CatalogPerfume],
    ) -> MatchResult | None:
        if not item.match_key:
            return None

        exact_candidates = [
            perfume
            for perfume in brand_candidates
            if item.match_key == perfume.match_key or item.match_key == perfume.slug_key
        ]
        if not exact_candidates:
            return None
        if len(exact_candidates) > 1:
            return MatchResult(
                status="needs_review",
                score=0.0,
                method="deterministic_key",
                perfume_id=None,
                perfume_name=None,
                match_reason="Multiple catalog perfumes share the same deterministic key.",
                match_components={"brand_score": 100, "name_score": 100},
            )

        perfume = exact_candidates[0]
        return MatchResult(
            status="matched_deterministic_key",
            score=100.0,
            method="deterministic_key",
            perfume_id=perfume.id,
            perfume_name=perfume.name,
            match_reason="Matched by deterministic brand/name key.",
            match_components={
                "brand_score": 100,
                "name_score": 100,
                "volume_match": self._optional_equal(item.volume_ml, perfume.volume_ml),
                "concentration_match": self._optional_equal(
                    item.concentration,
                    perfume.concentration,
                ),
            },
        )

    def _match_fuzzy(
        self,
        item: LoadedNormalizedItem,
        *,
        brand_candidates: list[CatalogPerfume],
        auto_threshold: int,
        review_threshold: int,
    ) -> MatchResult:
        scored_candidates: list[tuple[CatalogPerfume, float]] = []
        for perfume in brand_candidates:
            comparable_name = perfume.match_key or perfume.slug_key
            score = fuzzy_name_score(item.match_key or item.normalized_title, comparable_name)
            if score <= 0:
                continue
            if perfume.volume_ml is not None and item.volume_ml is not None:
                if perfume.volume_ml != item.volume_ml:
                    continue
                score = min(score + 2, 100.0)
            if perfume.concentration is not None and item.concentration is not None:
                if perfume.concentration != item.concentration:
                    continue
                score = min(score + 2, 100.0)
            scored_candidates.append((perfume, round(score, 2)))

        if not scored_candidates:
            return MatchResult(
                status="unmatched",
                score=0.0,
                method="none",
                perfume_id=None,
                perfume_name=None,
                match_reason="No brand-compatible fuzzy candidate met the minimum guardrails.",
                match_components={"brand_score": 100, "name_score": 0},
            )

        scored_candidates.sort(key=lambda entry: (-entry[1], entry[0].name, entry[0].id))
        best_perfume, best_score = scored_candidates[0]
        tied_best = [
            perfume for perfume, score in scored_candidates if abs(score - best_score) < 0.01
        ]
        if len(tied_best) > 1:
            return MatchResult(
                status="needs_review",
                score=best_score,
                method="fuzzy",
                perfume_id=None,
                perfume_name=None,
                match_reason=(
                    "Multiple brand-compatible catalog perfumes share the same fuzzy score."
                ),
                match_components={"brand_score": 100, "name_score": best_score},
            )

        if best_score >= auto_threshold:
            return MatchResult(
                status="matched_fuzzy",
                score=best_score,
                method="fuzzy",
                perfume_id=best_perfume.id,
                perfume_name=best_perfume.name,
                match_reason=f"Matched by guarded fuzzy score {best_score:.2f}.",
                match_components={
                    "brand_score": 100,
                    "name_score": best_score,
                    "volume_match": self._optional_equal(item.volume_ml, best_perfume.volume_ml),
                    "concentration_match": self._optional_equal(
                        item.concentration,
                        best_perfume.concentration,
                    ),
                },
            )
        if best_score >= review_threshold:
            return MatchResult(
                status="needs_review",
                score=best_score,
                method="fuzzy",
                perfume_id=best_perfume.id,
                perfume_name=best_perfume.name,
                match_reason=f"Fuzzy score {best_score:.2f} requires manual review.",
                match_components={"brand_score": 100, "name_score": best_score},
            )
        return MatchResult(
            status="unmatched",
            score=best_score,
            method="fuzzy",
            perfume_id=None,
            perfume_name=None,
            match_reason=f"Best fuzzy score {best_score:.2f} is below review threshold.",
            match_components={"brand_score": 100, "name_score": best_score},
        )

    def _missing_required_fields(self, item: LoadedNormalizedItem) -> list[str]:
        missing: list[str] = []
        if not item.title:
            missing.append("title")
        if not item.brand:
            missing.append("brand")
        if item.price is None:
            missing.append("price")
        if not item.affiliate_url:
            missing.append("affiliate_url")
        if not item.network_product_id and not item.merchant_product_id:
            missing.append("stable_external_id")
        return missing

    def _find_existing_offer(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        network_product_id: str | None,
        merchant_product_id: str | None,
    ) -> dict[str, object] | None:
        if network_product_id and merchant_product_id:
            rows = conn.execute(
                """
                select *
                from offers
                where advertiser_id = %s
                  and network_product_id = %s
                  and merchant_product_id = %s
                order by id
                """,
                (advertiser_db_id, network_product_id, merchant_product_id),
            ).fetchall()
        elif network_product_id:
            rows = conn.execute(
                """
                select *
                from offers
                where advertiser_id = %s
                  and network_product_id = %s
                order by id
                """,
                (advertiser_db_id, network_product_id),
            ).fetchall()
        elif merchant_product_id:
            rows = conn.execute(
                """
                select *
                from offers
                where advertiser_id = %s
                  and merchant_product_id = %s
                order by id
                """,
                (advertiser_db_id, merchant_product_id),
            ).fetchall()
        else:
            return None

        if len(rows) > 1:
            raise MatchingError(
                "Multiple existing offers share the same external identifiers for "
                f"advertiser_id={advertiser_db_id}, network_product_id={network_product_id}, "
                f"merchant_product_id={merchant_product_id}."
            )
        return dict(rows[0]) if rows else None

    def _upsert_offer(
        self,
        conn: Any,
        *,
        item: LoadedNormalizedItem,
        advertiser_db_id: int,
        network_feed_id: str,
        match_result: MatchResult,
    ) -> tuple[str, bool]:
        existing_offer = self._find_existing_offer(
            conn,
            advertiser_db_id=advertiser_db_id,
            network_product_id=item.network_product_id,
            merchant_product_id=item.merchant_product_id,
        )
        plan = self._plan_offer_upsert(
            existing_offer=existing_offer,
            item=item,
            network_feed_id=network_feed_id,
            match_result=match_result,
        )

        if existing_offer is None:
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
                    delivery_cost,
                    affiliate_url,
                    merchant_url,
                    image_url,
                    in_stock,
                    stock_status,
                    last_price_change_at,
                    missed_imports,
                    active,
                    match_status,
                    match_score,
                    match_method,
                    raw_payload,
                    metadata
                )
                values (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    now(), 0, true, %s, %s, %s, %s, %s
                )
                """,
                (
                    advertiser_db_id,
                    match_result.perfume_id,
                    item.network,
                    item.network_product_id,
                    item.merchant_product_id,
                    item.title,
                    item.description,
                    item.price,
                    item.currency or "EUR",
                    item.delivery_cost,
                    item.affiliate_url,
                    item.merchant_url,
                    item.image_url,
                    item.in_stock,
                    item.stock_status,
                    match_result.status,
                    Decimal(str(match_result.score)),
                    match_result.method,
                    Jsonb(item.raw_payload),
                    Jsonb(plan.merged_metadata),
                ),
            )
            return plan.action, plan.price_changed

        conn.execute(
            """
            update offers
            set perfume_id = %s,
                network = %s,
                network_product_id = %s,
                merchant_product_id = %s,
                title = %s,
                description = %s,
                price = %s,
                currency = %s,
                delivery_cost = %s,
                affiliate_url = %s,
                merchant_url = %s,
                image_url = %s,
                in_stock = %s,
                stock_status = %s,
                last_seen_at = now(),
                last_price_change_at = case
                    when price is distinct from %s then now()
                    else last_price_change_at
                end,
                missed_imports = 0,
                active = true,
                match_status = %s,
                match_score = %s,
                match_method = %s,
                raw_payload = %s,
                metadata = %s,
                updated_at = now()
            where id = %s
            """,
            (
                match_result.perfume_id,
                item.network,
                item.network_product_id,
                item.merchant_product_id,
                item.title,
                item.description,
                item.price,
                item.currency or "EUR",
                item.delivery_cost,
                item.affiliate_url,
                item.merchant_url,
                item.image_url,
                item.in_stock,
                item.stock_status,
                item.price,
                match_result.status,
                Decimal(str(match_result.score)),
                match_result.method,
                Jsonb(item.raw_payload),
                Jsonb(plan.merged_metadata),
                existing_offer["id"],
            ),
        )
        return plan.action, plan.price_changed

    def _build_offer_metadata(
        self,
        *,
        item: LoadedNormalizedItem,
        network_feed_id: str,
        match_result: MatchResult,
    ) -> dict[str, object]:
        metadata_source = (
            "reviewed_candidate"
            if match_result.method == "reviewed_candidate"
            else "pr07"
        )
        return {
            "feed_id": item.feed_id,
            "network_feed_id": network_feed_id,
            "normalized_feed_item_id": item.id,
            "raw_feed_item_id": item.raw_feed_item_id,
            "match_reason": match_result.match_reason,
            "match_components": match_result.match_components,
            "source": metadata_source,
        }

    def _plan_offer_upsert(
        self,
        *,
        existing_offer: dict[str, object] | None,
        item: LoadedNormalizedItem,
        network_feed_id: str,
        match_result: MatchResult,
    ) -> OfferUpsertPlan:
        metadata = self._build_offer_metadata(
            item=item,
            network_feed_id=network_feed_id,
            match_result=match_result,
        )
        if existing_offer is None:
            return OfferUpsertPlan(
                action="inserted",
                price_changed=True,
                merged_metadata=metadata,
                changed_fields=True,
            )

        price_changed = existing_offer["price"] != item.price
        existing_metadata = dict(existing_offer["metadata"] or {})
        merged_metadata = {**existing_metadata, **metadata}
        existing_raw_payload = dict(existing_offer["raw_payload"] or {})
        changed_fields = any(
            [
                (
                    str(existing_offer["perfume_id"])
                    if existing_offer["perfume_id"] is not None
                    else None
                )
                != match_result.perfume_id,
                existing_offer["title"] != item.title,
                existing_offer["description"] != item.description,
                existing_offer["price"] != item.price,
                existing_offer["currency"] != (item.currency or "EUR"),
                existing_offer["delivery_cost"] != item.delivery_cost,
                existing_offer["affiliate_url"] != item.affiliate_url,
                existing_offer["merchant_url"] != item.merchant_url,
                existing_offer["image_url"] != item.image_url,
                existing_offer["in_stock"] != item.in_stock,
                existing_offer["stock_status"] != item.stock_status,
                existing_raw_payload != item.raw_payload,
                existing_metadata != merged_metadata,
                existing_offer["match_status"] != match_result.status,
                float(existing_offer["match_score"] or 0) != match_result.score,
                existing_offer["match_method"] != match_result.method,
                existing_offer["active"] is not True,
                int(existing_offer["missed_imports"] or 0) != 0,
            ]
        )
        return OfferUpsertPlan(
            action="updated" if changed_fields else "unchanged",
            price_changed=price_changed,
            merged_metadata=merged_metadata,
            changed_fields=changed_fields,
        )

    def _update_stale_offers(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        network_feed_id: str,
        seen_offer_keys: set[tuple[str | None, str | None]],
        deactivate_after: int,
    ) -> tuple[int, int]:
        stale_offers_incremented = 0
        stale_offers_deactivated = 0
        rows = conn.execute(
            """
            select id, network_product_id, merchant_product_id, missed_imports, metadata
            from offers
            where advertiser_id = %s
              and active = true
              and coalesce(metadata ->> 'network_feed_id', '') = %s
            order by id
            """,
            (advertiser_db_id, network_feed_id),
        ).fetchall()

        for row in rows:
            if self._offer_seen_in_current_run(
                network_product_id=row["network_product_id"],
                merchant_product_id=row["merchant_product_id"],
                seen_offer_keys=seen_offer_keys,
            ):
                continue

            next_missed_imports = int(row["missed_imports"] or 0) + 1
            next_active = next_missed_imports < deactivate_after
            conn.execute(
                """
                update offers
                set missed_imports = %s,
                    active = %s,
                    updated_at = now()
                where id = %s
                """,
                (next_missed_imports, next_active, row["id"]),
            )
            stale_offers_incremented += 1
            if not next_active:
                stale_offers_deactivated += 1

        return stale_offers_incremented, stale_offers_deactivated

    def _offer_seen_in_current_run(
        self,
        *,
        network_product_id: str | None,
        merchant_product_id: str | None,
        seen_offer_keys: set[tuple[str | None, str | None]],
    ) -> bool:
        if network_product_id and merchant_product_id:
            return (network_product_id, merchant_product_id) in seen_offer_keys
        if network_product_id:
            return any(key[0] == network_product_id for key in seen_offer_keys)
        if merchant_product_id:
            return any(key[1] == merchant_product_id for key in seen_offer_keys)
        return False

    def _append_sample(
        self,
        report: dict[str, object],
        *,
        item: LoadedNormalizedItem,
        match_result: MatchResult,
    ) -> None:
        sample = {
            "normalized_feed_item_id": item.id,
            "raw_feed_item_id": item.raw_feed_item_id,
            "title": item.title,
            "brand": item.brand,
            "status": match_result.status,
            "score": match_result.score,
            "perfume_id": match_result.perfume_id,
            "perfume_name": match_result.perfume_name,
            "match_reason": match_result.match_reason,
        }
        if match_result.is_auto_match and len(report["sample_matches"]) < 5:
            report["sample_matches"].append(sample)
        elif match_result.status == "needs_review" and len(report["sample_needs_review"]) < 5:
            report["sample_needs_review"].append(sample)
        elif match_result.status == "unmatched" and len(report["sample_unmatched"]) < 5:
            report["sample_unmatched"].append(sample)

    def _increment_counter(self, counters: dict[str, object], key: str) -> None:
        counters[key] = int(counters.get(key, 0)) + 1

    def _optional_equal(self, left: object, right: object) -> bool | None:
        if left is None or right is None:
            return None
        return left == right


def format_matching_report_summary(report: Mapping[str, object], report_path: Path) -> str:
    lines = [
        f"status={report.get('status')}",
        f"dry_run={report.get('dry_run')}",
        f"import_run_id={report.get('import_run_id')}",
        f"normalized_rows_total={report.get('normalized_rows_total')}",
        f"rows_actionable_input={report.get('rows_actionable_input')}",
        f"rows_matched_total={report.get('rows_matched_total')}",
        f"rows_needs_review={report.get('rows_needs_review')}",
        f"rows_unmatched={report.get('rows_unmatched')}",
        f"offers_inserted={report.get('offers_inserted')}",
        f"offers_updated={report.get('offers_updated')}",
        f"offers_unchanged={report.get('offers_unchanged')}",
        f"stale_offers_incremented={report.get('stale_offers_incremented')}",
        f"stale_offers_deactivated={report.get('stale_offers_deactivated')}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)
