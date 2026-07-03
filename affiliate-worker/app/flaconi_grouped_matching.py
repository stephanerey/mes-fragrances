from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.awin_feed_mapping import canonicalize_row
from app.config import Settings
from app.db import DatabaseService
from app.matching import (
    CatalogPerfume,
    MatchingService,
    build_perfume_match_key,
    fuzzy_name_score,
)
from app.normalization import (
    AFFILIATE_URL_FIELDS,
    IMAGE_URL_FIELDS,
    PRICE_FIELDS,
    clean_identifier,
    detect_exclusion_reasons,
    extract_brand_fallback,
    is_fragrance_category,
    normalize_currency,
    normalize_text,
    parse_concentration,
    parse_price,
    parse_volume_ml,
)
from app.preprocessing import FeedPreprocessor, _read_csv_payload
from app.reporting import try_write_report, write_report


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


FLACONI_BRAND_ALIASES = {
    "rabanne": "paco rabanne",
    "aigner": "etienne aigner",
    "armani": "giorgio armani",
    "giorgio armani beauty": "giorgio armani",
    "ysl": "yves saint laurent",
    "saint laurent": "yves saint laurent",
    "viktor rolf": "viktor and rolf",
    "viktor&rolf": "viktor and rolf",
    "viktor and rolf fragrances": "viktor and rolf",
    "tiffany and company": "tiffany and co",
    "tiffany and co": "tiffany and co",
    "memo paris": "memo",
    "coach fragrances": "coach",
    "jimmy choo fragrances": "jimmy choo",
    "dolce gabbana": "dolce and gabbana",
    "dolcegabbana": "dolce and gabbana",
    "dolce gabbana beauty": "dolce and gabbana",
    "dolce gabanna": "dolce and gabbana",
    "zadig&voltaire": "zadig and voltaire",
    "zadig voltaire": "zadig and voltaire",
    "hermes": "hermes",
}
SAFE_GENERIC_TOKENS = {
    "eau",
    "de",
    "parfum",
    "toilette",
    "cologne",
    "spray",
    "vaporisateur",
    "natural",
    "refillable",
    "refill",
    "pour",
    "homme",
    "femme",
    "for",
    "men",
    "women",
    "her",
    "him",
}
FLANKER_TOKENS = {
    "absolu",
    "absolute",
    "black",
    "blue",
    "blossom",
    "coral",
    "elixir",
    "extreme",
    "fantasy",
    "intense",
    "intenso",
    "love",
    "night",
    "noir",
    "orchid",
    "rose",
    "rouge",
    "ruby",
    "sport",
    "vision",
}
GENDER_EQUIV = {
    "homme": {"homme", "for men", "for him", "pour homme", "men", "him"},
    "femme": {"femme", "for women", "for her", "pour femme", "women", "her"},
}


def _normalize_brand_for_matching(value: str | None) -> str:
    normalized = normalize_text(value)
    return FLACONI_BRAND_ALIASES.get(normalized, normalized)


def _expand_common_shorthand(value: str | None) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    replacements = {
        r"\bedp\b": " eau de parfum ",
        r"\bedt\b": " eau de toilette ",
        r"\bedc\b": " eau de cologne ",
        r"\bfor men\b": " homme ",
        r"\bfor him\b": " homme ",
        r"\bfor women\b": " femme ",
        r"\bfor her\b": " femme ",
        r"\bpour homme\b": " homme ",
        r"\bpour femme\b": " femme ",
    }
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_name_for_group(value: str | None, *, strip_brand: str | None = None) -> str:
    normalized = _expand_common_shorthand(value)
    if strip_brand:
        brand = normalize_text(strip_brand)
        if brand and normalized.startswith(brand + " "):
            normalized = normalized[len(brand) + 1 :]
    normalized = re.sub(r"\b\d{1,3}(?:[.,]\d+)?\s*(?:ml|cl|l|oz)\b", " ", normalized)
    normalized = re.sub(
        r"\b(vaporisateur|spray|natural spray|travel spray|refillable)\b", " ", normalized
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _tokens(value: str | None, *, strip_brand: str | None = None) -> set[str]:
    normalized = _normalize_name_for_group(value, strip_brand=strip_brand)
    return {token for token in normalized.split() if token and token not in SAFE_GENERIC_TOKENS}


def _parse_gender(value: str | None) -> str:
    text = _expand_common_shorthand(value)
    for canonical, variants in GENDER_EQUIV.items():
        if any(variant in text for variant in variants):
            return canonical
    return ""


def _gender_equivalent(source_text: str | None, catalog_gender: str | None) -> bool:
    source = _parse_gender(source_text)
    target = _parse_gender(catalog_gender)
    return bool(source and target and source == target)


def _decimal_to_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _price_to_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal("0.01")), "f")


def _parse_volume_from_fields(row: Mapping[str, str]) -> Decimal | None:
    fields = [
        row.get("product_name"),
        row.get("description"),
        row.get("merchant_category"),
        row.get("product_type"),
        row.get("keywords"),
        row.get("specifications"),
    ]
    text = " ".join(part for part in fields if part)
    return parse_volume_ml(text)


def _parse_concentration_from_fields(row: Mapping[str, str]) -> str | None:
    fields = [
        row.get("product_name"),
        row.get("description"),
        row.get("merchant_category"),
        row.get("product_type"),
        row.get("keywords"),
        row.get("specifications"),
    ]
    return parse_concentration(" ".join(part for part in fields if part))


def _select_affiliate_url(row: Mapping[str, str]) -> str | None:
    for field in AFFILIATE_URL_FIELDS:
        value = (row.get(field) or "").strip()
        if value:
            return value
    return None


def _select_image_url(row: Mapping[str, str]) -> str | None:
    for field in IMAGE_URL_FIELDS:
        value = (row.get(field) or "").strip()
        if value:
            return value
    return None


def _clean_identifier_map(row: Mapping[str, str]) -> dict[str, str]:
    return {
        "ean": clean_identifier(row.get("ean")) or "",
        "gtin": clean_identifier(row.get("product_GTIN")) or "",
        "upc": clean_identifier(row.get("upc")) or "",
        "mpn": clean_identifier(row.get("mpn")) or "",
    }


@dataclass(frozen=True)
class GroupedSourceRow:
    flaconi_product_id: str
    merchant_product_id: str | None
    brand: str
    normalized_brand: str
    alias_brand: str
    source_name: str
    normalized_name: str
    concentration: str | None
    volume_ml: Decimal | None
    price: Decimal | None
    currency: str
    affiliate_url: str | None
    image_url: str | None
    category: str | None
    merchant_category: str | None
    product_type: str | None
    description: str | None
    identifiers: dict[str, str]
    is_fragrance: bool
    exclusion_reasons: list[str]
    raw_payload: dict[str, str]


@dataclass(frozen=True)
class CatalogOfferState:
    perfume_id: str
    has_any_offer: bool
    has_available_offer: bool
    has_perfumeria_offer: bool
    has_flaconi_offer: bool
    best_available_price: Decimal | None


@dataclass(frozen=True)
class GroupCandidate:
    perfume: CatalogPerfume
    score: float
    method: str
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class GroupedOffer:
    group_id: str
    group_key: str
    rows: tuple[GroupedSourceRow, ...]
    representative: GroupedSourceRow
    classification: str
    volume_detection_status: str
    risk_flags: tuple[str, ...]
    best_match: GroupCandidate | None
    second_match: GroupCandidate | None


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    headers = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _source_row_to_dict(row: GroupedSourceRow) -> dict[str, object]:
    return {
        "flaconi_product_id": row.flaconi_product_id,
        "merchant_product_id": row.merchant_product_id or "",
        "brand": row.brand,
        "normalized_brand": row.normalized_brand,
        "alias_brand": row.alias_brand,
        "source_name": row.source_name,
        "normalized_name": row.normalized_name,
        "concentration": row.concentration or "",
        "volume_ml": _decimal_to_string(row.volume_ml),
        "price": _price_to_string(row.price),
        "currency": row.currency,
        "affiliate_url_present": "true" if row.affiliate_url else "false",
        "image_url_present": "true" if row.image_url else "false",
        "category": row.category or "",
        "merchant_category": row.merchant_category or "",
        "product_type": row.product_type or "",
        "identifiers": " | ".join(value for value in row.identifiers.values() if value),
        "is_fragrance": "true" if row.is_fragrance else "false",
        "exclusion_reasons": ",".join(row.exclusion_reasons),
    }


def _catalog_offer_state(
    conn: Any,
    *,
    flaconi_advertiser_network_id: str,
    perfumeria_advertiser_network_id: str,
) -> dict[str, CatalogOfferState]:
    rows = conn.execute(
        """
        select
            o.perfume_id::text as perfume_id,
            count(*)::integer as offer_count,
            count(*) filter (
                where o.active is true
                  and o.price is not null
                  and o.affiliate_url is not null
            )::integer as available_offer_count,
            bool_or(a.network_advertiser_id = %s) as has_flaconi_offer,
            bool_or(a.network_advertiser_id = %s) as has_perfumeria_offer,
            min(o.price) filter (
                where o.active is true
                  and o.price is not null
                  and o.affiliate_url is not null
            ) as best_available_price
        from offers o
        join advertisers a on a.id = o.advertiser_id
        group by o.perfume_id
        """,
        (flaconi_advertiser_network_id, perfumeria_advertiser_network_id),
    ).fetchall()
    result: dict[str, CatalogOfferState] = {}
    for row in rows:
        result[str(row["perfume_id"])] = CatalogOfferState(
            perfume_id=str(row["perfume_id"]),
            has_any_offer=int(row["offer_count"] or 0) > 0,
            has_available_offer=int(row["available_offer_count"] or 0) > 0,
            has_perfumeria_offer=bool(row["has_perfumeria_offer"]),
            has_flaconi_offer=bool(row["has_flaconi_offer"]),
            best_available_price=row["best_available_price"],
        )
    return result


def _build_catalog_indexes(
    perfumes: Iterable[CatalogPerfume],
) -> tuple[dict[str, list[CatalogPerfume]], dict[tuple[str, str], list[CatalogPerfume]]]:
    by_brand: dict[str, list[CatalogPerfume]] = defaultdict(list)
    by_identifier: dict[tuple[str, str], list[CatalogPerfume]] = defaultdict(list)
    for perfume in perfumes:
        brand_key = _normalize_brand_for_matching(perfume.brand)
        by_brand[brand_key].append(perfume)
        for field, value in perfume.identifiers.items():
            if value:
                by_identifier[(field, value)].append(perfume)
    return by_brand, by_identifier


def _significant_missing_tokens(
    source_name: str,
    target_name: str,
    *,
    source_brand: str,
    target_brand: str,
) -> list[str]:
    source_tokens = _tokens(source_name, strip_brand=source_brand)
    target_tokens = _tokens(target_name, strip_brand=target_brand)
    return sorted(
        token
        for token in (source_tokens - target_tokens)
        if len(token) >= 4 and token not in FLANKER_TOKENS
    )


def _best_catalog_candidates(
    row: GroupedSourceRow,
    *,
    catalog_by_brand: dict[str, list[CatalogPerfume]],
    catalog_by_identifier: dict[tuple[str, str], list[CatalogPerfume]],
) -> list[GroupCandidate]:
    candidates: list[GroupCandidate] = []
    seen: set[str] = set()

    for field, value in row.identifiers.items():
        if not value:
            continue
        matches = catalog_by_identifier.get((field, value), [])
        for perfume in matches:
            if perfume.id in seen:
                continue
            seen.add(perfume.id)
            candidates.append(
                GroupCandidate(
                    perfume=perfume,
                    score=1.0,
                    method=f"identifier_{field}",
                    risk_flags=(),
                )
            )
    if candidates:
        return sorted(candidates, key=lambda c: (-c.score, c.perfume.name, c.perfume.id))

    brand_candidates = catalog_by_brand.get(row.alias_brand, [])
    for perfume in brand_candidates:
        if perfume.id in seen:
            continue
        score = max(
            fuzzy_name_score(row.normalized_name, perfume.match_key) / 100,
            fuzzy_name_score(row.normalized_name, perfume.slug_key) / 100
            if perfume.slug_key
            else 0.0,
        )
        if score <= 0.58:
            continue
        risk_flags: list[str] = []
        if row.alias_brand != row.normalized_brand:
            risk_flags.append("brand_alias_used")
        if row.volume_ml is not None and perfume.volume_ml is not None:
            if row.volume_ml == perfume.volume_ml:
                score = min(score + 0.04, 0.999)
            else:
                risk_flags.append("volume_mismatch")
        if row.concentration and perfume.concentration:
            if row.concentration == perfume.concentration.lower():
                score = min(score + 0.04, 0.999)
            else:
                risk_flags.append("concentration_mismatch")
        if _gender_equivalent(row.source_name, perfume.name):
            score = min(score + 0.02, 0.999)

        missing_tokens = _significant_missing_tokens(
            row.source_name,
            perfume.name,
            source_brand=row.brand,
            target_brand=perfume.brand,
        )
        if missing_tokens:
            risk_flags.append("missing_tokens:" + ",".join(missing_tokens[:5]))

        source_variant_tokens = _tokens(row.source_name, strip_brand=row.brand) & FLANKER_TOKENS
        target_variant_tokens = _tokens(perfume.name, strip_brand=perfume.brand) & FLANKER_TOKENS
        if source_variant_tokens != target_variant_tokens and source_variant_tokens:
            risk_flags.append("variant_wording_diff")

        seen.add(perfume.id)
        candidates.append(
            GroupCandidate(
                perfume=perfume,
                score=min(score, 0.999),
                method="brand_name_similarity",
                risk_flags=tuple(sorted(set(risk_flags))),
            )
        )

    return sorted(candidates, key=lambda c: (-c.score, c.perfume.name, c.perfume.id))[:10]


def _volume_status(rows: list[GroupedSourceRow]) -> str:
    volumes = {row.volume_ml for row in rows if row.volume_ml is not None}
    if len(volumes) > 1:
        return "mixed_detected"
    if len(rows) == 1:
        return "known_single" if volumes else "unknown_single"
    if volumes:
        return "known_multi_row_same_volume"
    return "unknown_multi_row"


def _representative_row(rows: list[GroupedSourceRow]) -> GroupedSourceRow:
    return sorted(
        rows,
        key=lambda row: (
            row.price if row.price is not None else Decimal("999999"),
            row.flaconi_product_id,
            row.merchant_product_id or "",
        ),
    )[0]


def _group_key(row: GroupedSourceRow) -> str:
    volume_part = _decimal_to_string(row.volume_ml)
    return "|".join(
        [
            row.alias_brand,
            row.normalized_name,
            row.concentration or "",
            volume_part,
        ]
    )


def _group_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _risk_flags_for_group(rows: list[GroupedSourceRow], volume_status: str) -> set[str]:
    flags: set[str] = set()
    price_values = {row.price for row in rows if row.price is not None}
    external_ids = {value for row in rows for value in row.identifiers.values() if value}
    if len(rows) > 1:
        flags.add("duplicate_source_rows")
    if len(price_values) > 1:
        flags.add("multiple_prices")
    if len(external_ids) > 1:
        flags.add("multiple_external_ids")
    if volume_status == "unknown_multi_row":
        flags.add("volume_unknown_multi_row")
    elif volume_status == "mixed_detected":
        flags.add("volume_mismatch")
    return flags


def _classify_group(
    rows: list[GroupedSourceRow],
    *,
    candidates: list[GroupCandidate],
    offer_state: Mapping[str, CatalogOfferState],
) -> tuple[str, tuple[str, ...], GroupCandidate | None, GroupCandidate | None]:
    volume_status = _volume_status(rows)
    risk_flags = _risk_flags_for_group(rows, volume_status)

    if any("set_or_bundle" in row.exclusion_reasons for row in rows):
        return (
            "GROUP_BLOCKED_SET_OR_BUNDLE",
            tuple(sorted(risk_flags | {"set_or_bundle"})),
            None,
            None,
        )
    if any(
        reason in {"body_product", "home_fragrance", "tester"}
        for row in rows
        for reason in row.exclusion_reasons
    ):
        return "GROUP_BLOCKED_NON_PERFUME", tuple(sorted(risk_flags | {"non_perfume"})), None, None

    best = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    if best is not None:
        best_flags = set(best.risk_flags)
        if second is not None and second.score >= best.score - 0.03 and second.score >= 0.78:
            return (
                "EXISTING_GROUP_CONFLICT",
                tuple(sorted(risk_flags | best_flags | {"multiple_close_targets"})),
                best,
                second,
            )
        if any(
            flag.startswith("missing_tokens:") and "jaipure" in flag for flag in best.risk_flags
        ):
            return (
                "GROUP_BLOCKED_VARIANT_CONFLICT",
                tuple(sorted(risk_flags | best_flags | {"known_false_positive_boucheron_jaipure"})),
                best,
                second,
            )
        if "variant_wording_diff" in best_flags:
            return (
                "GROUP_BLOCKED_VARIANT_CONFLICT",
                tuple(sorted(risk_flags | best_flags)),
                best,
                second,
            )

        state = offer_state.get(best.perfume.id)
        if state and state.has_flaconi_offer:
            return (
                "EXISTING_GROUP_ALREADY_HAS_FLACONI",
                tuple(sorted(risk_flags | best_flags)),
                best,
                second,
            )

        target_has_precise_volume = best.perfume.volume_ml is not None
        if volume_status == "unknown_multi_row" and target_has_precise_volume:
            return (
                "GROUP_BLOCKED_VOLUME_UNKNOWN",
                tuple(sorted(risk_flags | best_flags)),
                best,
                second,
            )
        if best.score >= 0.92 and not best_flags:
            return (
                "EXISTING_GROUP_STRONG_TO_CREATE_OFFER",
                tuple(sorted(risk_flags)),
                best,
                second,
            )
        if best.score >= 0.92 and best_flags <= {"brand_alias_used"}:
            return (
                "EXISTING_GROUP_STRONG_TO_CREATE_OFFER",
                tuple(sorted(risk_flags | best_flags)),
                best,
                second,
            )
        if (
            best.score >= 0.92
            and "concentration_mismatch" not in best_flags
            and "volume_mismatch" not in best_flags
        ):
            return (
                "EXISTING_GROUP_REVIEW_TO_CREATE_OFFER",
                tuple(sorted(risk_flags | best_flags)),
                best,
                second,
            )
        if best.score >= 0.78:
            return (
                "EXISTING_GROUP_REVIEW_TO_CREATE_OFFER",
                tuple(sorted(risk_flags | best_flags)),
                best,
                second,
            )

    if volume_status == "unknown_multi_row":
        return "GROUP_BLOCKED_VOLUME_UNKNOWN", tuple(sorted(risk_flags)), best, second

    group_brand_exists = bool(candidates)
    if group_brand_exists:
        return "NEW_PERFUME_GROUP_REVIEW", tuple(sorted(risk_flags)), best, second
    return "NEW_PERFUME_GROUP_STRONG", tuple(sorted(risk_flags)), best, second


class FlaconiGroupedMatchingError(RuntimeError):
    """Raised when grouped Flaconi dry-run analysis cannot complete safely."""


class FlaconiGroupedMatchingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_service = DatabaseService(settings)
        self.preprocessor = FeedPreprocessor(settings)
        self.matching_service = MatchingService(settings)

    def analyze(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        report_dir: Path,
        path: Path | None = None,
    ) -> tuple[dict[str, object], Path]:
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "flaconi-grouped-dry-run",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "database_write_performed": False,
        }

        try:
            source = self.preprocessor._resolve_source(
                advertiser_id=advertiser_id, feed_id=feed_id, path=path
            )
            header, raw_rows, _, compression = _read_csv_payload(
                source.payload,
                delimiter_hint=source.delimiter_hint,
            )
            canonical_rows = [
                canonicalize_row(row, advertiser_id=advertiser_id, feed_id=feed_id)
                for row in raw_rows
            ]
            normalized_rows = [self._normalize_source_row(row) for row in canonical_rows]
            usable_rows = [
                row
                for row in normalized_rows
                if row.is_fragrance
                and not row.exclusion_reasons
                and row.price is not None
                and row.affiliate_url
            ]
            grouped = self._build_groups(usable_rows)

            with self.db_service.connect() as conn:
                catalog_rows, _ = self.matching_service._load_catalog_perfumes(conn)
                catalog_by_brand, catalog_by_identifier = _build_catalog_indexes(catalog_rows)
                offer_state = _catalog_offer_state(
                    conn,
                    flaconi_advertiser_network_id=advertiser_id,
                    perfumeria_advertiser_network_id="105475",
                )
                states = {
                    "public.perfumes": self._scalar(conn, "select count(*) from public.perfumes"),
                    "public.offers": self._scalar(conn, "select count(*) from public.offers"),
                    "product_match_candidates": self._scalar(
                        conn, "select count(*) from public.product_match_candidates"
                    ),
                    "perfume_insert_candidates": self._scalar(
                        conn, "select count(*) from public.perfume_insert_candidates"
                    ),
                    "advertiser_active": self._scalar(
                        conn,
                        (
                            "select coalesce(active::text,'') "
                            "from public.advertisers "
                            "where network='awin' and network_advertiser_id = %s"
                        ),
                        (advertiser_id,),
                    ),
                    "feed_active": self._scalar(
                        conn,
                        (
                            "select coalesce(active::text,'') "
                            "from public.affiliate_feeds "
                            "where network='awin' and network_feed_id = %s"
                        ),
                        (feed_id,),
                    ),
                }

            analyzed_groups: list[GroupedOffer] = []
            for group_rows in grouped.values():
                representative = _representative_row(group_rows)
                candidates = _best_catalog_candidates(
                    representative,
                    catalog_by_brand=catalog_by_brand,
                    catalog_by_identifier=catalog_by_identifier,
                )
                classification, risk_flags, best, second = _classify_group(
                    group_rows,
                    candidates=candidates,
                    offer_state=offer_state,
                )
                group_key = _group_key(representative)
                analyzed_groups.append(
                    GroupedOffer(
                        group_id=_group_id(group_key),
                        group_key=group_key,
                        rows=tuple(group_rows),
                        representative=representative,
                        classification=classification,
                        volume_detection_status=_volume_status(group_rows),
                        risk_flags=risk_flags,
                        best_match=best,
                        second_match=second,
                    )
                )

            report_dir.mkdir(parents=True, exist_ok=True)
            grouped_inventory_rows = self._grouped_inventory_rows(analyzed_groups)
            grouped_inventory_summary_rows = self._grouped_summary_rows(analyzed_groups)
            matches_rows = self._grouped_match_rows(analyzed_groups, offer_state)
            matches_summary_rows = self._grouped_match_summary_rows(analyzed_groups)
            phase1_ready_rows = self._phase1_ready_rows(analyzed_groups, offer_state)
            phase2_review_rows = self._phase2_review_rows(analyzed_groups, offer_state)
            phase3_new_rows = self._phase3_new_rows(analyzed_groups)
            blocked_rows = self._blocked_rows(analyzed_groups)

            grouped_inventory_path = report_dir / "grouped_inventory.csv"
            grouped_inventory_summary_path = report_dir / "grouped_inventory_summary.csv"
            matches_path = report_dir / "grouped_matches_all_catalog.csv"
            matches_summary_path = report_dir / "grouped_matches_all_catalog_summary.csv"
            phase1_ready_path = report_dir / "phase1_existing_group_strong_ready.csv"
            phase2_review_path = report_dir / "phase2_existing_group_review.csv"
            phase3_new_path = report_dir / "phase3_new_perfume_groups.csv"
            blocked_path = report_dir / "blocked_groups_for_later.csv"

            _write_csv(grouped_inventory_path, grouped_inventory_rows)
            _write_csv(grouped_inventory_summary_path, grouped_inventory_summary_rows)
            _write_csv(matches_path, matches_rows)
            _write_csv(matches_summary_path, matches_summary_rows)
            _write_csv(phase1_ready_path, phase1_ready_rows)
            _write_csv(phase2_review_path, phase2_review_rows)
            _write_csv(phase3_new_path, phase3_new_rows)
            _write_csv(blocked_path, blocked_rows)

            classification_counts = Counter(group.classification for group in analyzed_groups)
            report.update(
                {
                    "status": "success",
                    "source": source.source,
                    "source_reference": source.source_reference,
                    "compression": source.compression_hint or compression,
                    "header_count": len(header),
                    "rows_total": len(canonical_rows),
                    "rows_usable_fragrance": len(usable_rows),
                    "group_count": len(analyzed_groups),
                    "group_classification_counts": dict(sorted(classification_counts.items())),
                    "grouped_inventory_path": str(grouped_inventory_path),
                    "matches_path": str(matches_path),
                    "phase1_ready_path": str(phase1_ready_path),
                    "phase2_review_path": str(phase2_review_path),
                    "phase3_new_path": str(phase3_new_path),
                    "blocked_path": str(blocked_path),
                    "db_state": states,
                }
            )
            report_path = write_report(report_dir, "flaconi_grouped_matching", report)
            return report, report_path
        except Exception as exc:
            report["error"] = str(exc)
            report_path = try_write_report(report_dir, "flaconi_grouped_matching_error", report)
            if report_path is not None:
                raise FlaconiGroupedMatchingError(
                    f"{exc}. Report written to {report_path}"
                ) from exc
            raise FlaconiGroupedMatchingError(str(exc)) from exc

    def _scalar(self, conn: Any, sql: str, params: tuple[object, ...] = ()) -> str:
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return ""
        return str(next(iter(dict(row).values())))

    def _normalize_source_row(self, row: Mapping[str, str]) -> GroupedSourceRow:
        title = (row.get("product_name") or "").strip()
        description = (row.get("description") or "").strip() or None
        brand = (row.get("brand_name") or "").strip() or extract_brand_fallback(title) or ""
        category = (row.get("category_name") or "").strip() or None
        merchant_category = (row.get("merchant_category") or "").strip() or None
        product_type = (row.get("product_type") or "").strip() or None
        price = parse_price(*(row.get(field) for field in PRICE_FIELDS))
        affiliate_url = _select_affiliate_url(row)
        concentration = _parse_concentration_from_fields(row)
        volume_ml = _parse_volume_from_fields(row)
        exclusion_reasons = detect_exclusion_reasons(
            title,
            description,
            merchant_category,
            product_type,
            row.get("keywords"),
            row.get("specifications"),
        )
        is_fragrance = is_fragrance_category(category, merchant_category or product_type)
        return GroupedSourceRow(
            flaconi_product_id=(row.get("aw_product_id") or "").strip(),
            merchant_product_id=(row.get("merchant_product_id") or "").strip() or None,
            brand=brand,
            normalized_brand=normalize_text(brand),
            alias_brand=_normalize_brand_for_matching(brand),
            source_name=title,
            normalized_name=build_perfume_match_key(
                title,
                brand=brand,
                concentration=concentration,
                volume_ml=volume_ml,
            ),
            concentration=concentration,
            volume_ml=volume_ml,
            price=price,
            currency=normalize_currency(row.get("currency")),
            affiliate_url=affiliate_url,
            image_url=_select_image_url(row),
            category=category,
            merchant_category=merchant_category,
            product_type=product_type,
            description=description,
            identifiers=_clean_identifier_map(row),
            is_fragrance=is_fragrance,
            exclusion_reasons=exclusion_reasons,
            raw_payload=dict(row),
        )

    def _build_groups(
        self, usable_rows: list[GroupedSourceRow]
    ) -> dict[str, list[GroupedSourceRow]]:
        groups: dict[str, list[GroupedSourceRow]] = defaultdict(list)
        for row in usable_rows:
            groups[_group_key(row)].append(row)
        return groups

    def _grouped_inventory_rows(self, groups: list[GroupedOffer]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group in sorted(groups, key=lambda item: (item.classification, item.group_id)):
            source_rows = list(group.rows)
            prices = [row.price for row in source_rows]
            volumes = {row.volume_ml for row in source_rows if row.volume_ml is not None}
            identifiers = {
                value for row in source_rows for value in row.identifiers.values() if value
            }
            rows.append(
                {
                    "group_id": group.group_id,
                    "group_key": group.group_key,
                    "source_rows_count": len(source_rows),
                    "source_product_ids": "|".join(row.flaconi_product_id for row in source_rows),
                    "brand": group.representative.brand,
                    "normalized_brand": group.representative.alias_brand,
                    "display_name": group.representative.source_name,
                    "normalized_name": group.representative.normalized_name,
                    "concentration": group.representative.concentration or "",
                    "volume_ml": _decimal_to_string(group.representative.volume_ml),
                    "price_min": _price_to_string(min(prices)),
                    "price_max": _price_to_string(max(prices)),
                    "representative_price": _price_to_string(group.representative.price),
                    "representative_currency": group.representative.currency,
                    "representative_affiliate_url_present": "true",
                    "has_multiple_gtin": "true" if len(identifiers) > 1 else "false",
                    "has_multiple_prices": "true" if len(set(prices)) > 1 else "false",
                    "has_multiple_volumes": "true" if len(volumes) > 1 else "false",
                    "volume_detection_status": group.volume_detection_status,
                    "group_classification": group.classification,
                    "risk_flags": ",".join(group.risk_flags),
                }
            )
        return rows

    def _grouped_summary_rows(self, groups: list[GroupedOffer]) -> list[dict[str, object]]:
        counts = Counter(group.classification for group in groups)
        rows = [
            {
                "summary_type": "group_classification",
                "key": key,
                "value": value,
                "notes": "",
            }
            for key, value in sorted(counts.items())
        ]
        rows.append(
            {
                "summary_type": "groups_total",
                "key": "all",
                "value": len(groups),
                "notes": "grouped Flaconi opportunities after dedup",
            }
        )
        rows.append(
            {
                "summary_type": "source_rows_total",
                "key": "usable_fragrance",
                "value": sum(len(group.rows) for group in groups),
                "notes": "usable fragrance source rows represented by the groups",
            }
        )
        return rows

    def _grouped_match_rows(
        self,
        groups: list[GroupedOffer],
        offer_state: Mapping[str, CatalogOfferState],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group in groups:
            best = group.best_match
            perfume_state = offer_state.get(best.perfume.id) if best else None
            current_best_price = perfume_state.best_available_price if perfume_state else None
            flaconi_price = group.representative.price
            cheaper = ""
            if current_best_price is not None:
                if flaconi_price < current_best_price:
                    cheaper = "true"
                elif flaconi_price > current_best_price:
                    cheaper = "false"
                else:
                    cheaper = "equal"
            rows.append(
                {
                    "group_id": group.group_id,
                    "flaconi_product_id": group.representative.flaconi_product_id,
                    "source_brand": group.representative.brand,
                    "source_name": group.representative.source_name,
                    "source_price": _price_to_string(group.representative.price),
                    "source_currency": group.representative.currency,
                    "matched_perfume_id": best.perfume.id if best else "",
                    "matched_perfume_brand": best.perfume.brand if best else "",
                    "matched_perfume_name": best.perfume.name if best else "",
                    "matched_perfume_concentration": best.perfume.concentration or ""
                    if best
                    else "",
                    "matched_perfume_volume_ml": _decimal_to_string(best.perfume.volume_ml)
                    if best
                    else "",
                    "matched_perfume_has_any_offer": "true"
                    if perfume_state and perfume_state.has_any_offer
                    else "false",
                    "matched_perfume_has_perfumeria_offer": "true"
                    if perfume_state and perfume_state.has_perfumeria_offer
                    else "false",
                    "matched_perfume_has_flaconi_offer": "true"
                    if perfume_state and perfume_state.has_flaconi_offer
                    else "false",
                    "matched_perfume_has_available_offer": "true"
                    if perfume_state and perfume_state.has_available_offer
                    else "false",
                    "existing_best_price": _price_to_string(current_best_price),
                    "flaconi_price": _price_to_string(flaconi_price),
                    "flaconi_is_cheaper_than_current_best": cheaper,
                    "match_category": group.classification,
                    "match_score": f"{best.score:.3f}" if best else "",
                    "match_reason": best.method if best else "no_match",
                    "risk_flags": ",".join(
                        group.risk_flags
                        if not best
                        else tuple(sorted(set(group.risk_flags) | set(best.risk_flags)))
                    ),
                    "recommended_action": group.classification,
                }
            )
        return rows

    def _grouped_match_summary_rows(self, groups: list[GroupedOffer]) -> list[dict[str, object]]:
        counts = Counter(group.classification for group in groups)
        return [
            {
                "summary_type": "match_category",
                "key": key,
                "value": value,
                "notes": "",
            }
            for key, value in sorted(counts.items())
        ]

    def _phase1_ready_rows(
        self,
        groups: list[GroupedOffer],
        offer_state: Mapping[str, CatalogOfferState],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group in groups:
            best = group.best_match
            if best is None or group.classification != "EXISTING_GROUP_STRONG_TO_CREATE_OFFER":
                continue
            if normalize_text(group.representative.brand) in {"dolce and gabbana", "d and g", "dg"}:
                continue
            if "jaipure" in normalize_text(group.representative.source_name):
                continue
            state = offer_state.get(best.perfume.id)
            current_best_price = state.best_available_price if state else None
            if current_best_price is None:
                price_relation = "no_current_price"
            elif group.representative.price < current_best_price:
                price_relation = "cheaper"
            elif group.representative.price > current_best_price:
                price_relation = "more_expensive"
            else:
                price_relation = "equal"
            rows.append(
                {
                    "group_id": group.group_id,
                    "source_rows_count": len(group.rows),
                    "flaconi_product_id": group.representative.flaconi_product_id,
                    "advertiser_id": "87361",
                    "feed_id": "97463",
                    "source_brand": group.representative.brand,
                    "source_name": group.representative.source_name,
                    "source_price": _price_to_string(group.representative.price),
                    "source_currency": group.representative.currency,
                    "matched_perfume_id": best.perfume.id,
                    "matched_perfume_brand": best.perfume.brand,
                    "matched_perfume_name": best.perfume.name,
                    "matched_perfume_has_any_offer": "true"
                    if state and state.has_any_offer
                    else "false",
                    "matched_perfume_has_perfumeria_offer": "true"
                    if state and state.has_perfumeria_offer
                    else "false",
                    "matched_perfume_has_flaconi_offer": "true"
                    if state and state.has_flaconi_offer
                    else "false",
                    "current_best_price": _price_to_string(current_best_price),
                    "price_relation": price_relation,
                    "match_score": f"{best.score:.3f}",
                    "match_reason": best.method,
                    "risk_flags": ",".join(group.risk_flags),
                }
            )
        return rows

    def _phase2_review_rows(
        self,
        groups: list[GroupedOffer],
        offer_state: Mapping[str, CatalogOfferState],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group in groups:
            best = group.best_match
            if best is None or group.classification != "EXISTING_GROUP_REVIEW_TO_CREATE_OFFER":
                continue
            state = offer_state.get(best.perfume.id)
            rows.append(
                {
                    "group_id": group.group_id,
                    "source_rows_count": len(group.rows),
                    "flaconi_product_id": group.representative.flaconi_product_id,
                    "source_brand": group.representative.brand,
                    "source_name": group.representative.source_name,
                    "source_price": _price_to_string(group.representative.price),
                    "matched_perfume_id": best.perfume.id,
                    "matched_perfume_brand": best.perfume.brand,
                    "matched_perfume_name": best.perfume.name,
                    "matched_perfume_has_any_offer": "true"
                    if state and state.has_any_offer
                    else "false",
                    "matched_perfume_has_perfumeria_offer": "true"
                    if state and state.has_perfumeria_offer
                    else "false",
                    "match_score": f"{best.score:.3f}",
                    "match_reason": best.method,
                    "risk_flags": ",".join(
                        group.risk_flags
                        if not best
                        else tuple(sorted(set(group.risk_flags) | set(best.risk_flags)))
                    ),
                }
            )
        return rows

    def _phase3_new_rows(self, groups: list[GroupedOffer]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group in groups:
            if group.classification not in {"NEW_PERFUME_GROUP_STRONG", "NEW_PERFUME_GROUP_REVIEW"}:
                continue
            rows.append(
                {
                    "group_id": group.group_id,
                    "source_rows_count": len(group.rows),
                    "flaconi_product_id": group.representative.flaconi_product_id,
                    "brand": group.representative.brand,
                    "name": group.representative.source_name,
                    "concentration": group.representative.concentration or "",
                    "volume_ml": _decimal_to_string(group.representative.volume_ml),
                    "price": _price_to_string(group.representative.price),
                    "currency": group.representative.currency,
                    "group_classification": group.classification,
                    "risk_flags": ",".join(group.risk_flags),
                }
            )
        return rows

    def _blocked_rows(self, groups: list[GroupedOffer]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group in groups:
            if (
                not group.classification.startswith("GROUP_BLOCKED")
                and group.classification != "EXISTING_GROUP_CONFLICT"
            ):
                continue
            rows.append(
                {
                    "group_id": group.group_id,
                    "source_rows_count": len(group.rows),
                    "flaconi_product_id": group.representative.flaconi_product_id,
                    "brand": group.representative.brand,
                    "name": group.representative.source_name,
                    "group_classification": group.classification,
                    "risk_flags": ",".join(group.risk_flags),
                    "matched_perfume_id": group.best_match.perfume.id if group.best_match else "",
                    "matched_perfume_name": group.best_match.perfume.name
                    if group.best_match
                    else "",
                }
            )
        return rows


def format_grouped_matching_summary(report: Mapping[str, object], report_path: Path) -> str:
    lines = [
        f"status={report.get('status')}",
        f"advertiser_id={report.get('advertiser_id')}",
        f"feed_id={report.get('feed_id')}",
        f"rows_total={report.get('rows_total')}",
        f"rows_usable_fragrance={report.get('rows_usable_fragrance')}",
        f"group_count={report.get('group_count')}",
        f"report_path={report_path}",
    ]
    counts = report.get("group_classification_counts") or {}
    if isinstance(counts, Mapping):
        for key in sorted(counts):
            lines.append(f"{key}={counts[key]}")
    return "\n".join(lines)
