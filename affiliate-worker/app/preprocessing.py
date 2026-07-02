from __future__ import annotations

import csv
import gzip
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from app.awin import (
    GZIP_MAGIC,
    AwinCommandError,
    AwinFetcher,
    AwinService,
    find_feed,
    get_configured_feed_url,
    parse_download_url_metadata,
    redact_url,
)
from app.awin_feed_mapping import canonicalize_row, compare_columns
from app.config import Settings
from app.reporting import try_write_report, write_report

AFFILIATE_URL_FIELDS = ("aw_deep_link", "merchant_deep_link")
PRICE_FIELDS = ("search_price", "display_price", "store_price")
STOCK_FIELDS = ("in_stock", "stock_quantity", "stock_status")
IMAGE_FIELDS = (
    "large_image",
    "merchant_image_url",
    "aw_image_url",
    "merchant_thumb_url",
    "alternate_image",
    "alternate_image_two",
    "alternate_image_three",
    "alternate_image_four",
)
CATEGORY_PATH_FIELDS = (
    "merchant_product_category_path",
    "merchant_product_second_category",
    "merchant_product_third_category",
)
FRAGRANCE_CATEGORY_ALIASES = {
    "fragrance",
    "fragrances",
    "parfum",
    "parfums",
    "perfume",
    "perfumes",
    "duft",
    "damenduft",
    "herrenduft",
}
FRAGRANCE_CATEGORY_EXCLUDED_PHRASES = {
    "parfum d ambiance",
    "parfum d'ambiance",
    "diffuseur de parfum",
    "coffret de parfum d ambiance",
    "brule parfum",
    "parfum cheveux",
    "hair perfume",
}
CONCENTRATION_PATTERNS = (
    (r"\bextrait de parfum\b|\bperfume extract\b|\bextrait\b", "EXTRAIT"),
    (r"\beau de parfum\b|\bedp\b", "EDP"),
    (r"\beau de toilette\b|\bedt\b", "EDT"),
    (r"\beau de cologne\b|\bedc\b", "EDC"),
    (r"\beau fraiche\b", "EAU_FRAICHE"),
    (r"\bparfum\b", "PARFUM"),
)
EXCLUSION_KEYWORDS = {
    "set_or_bundle": ("coffret", "set", "duo", "trio"),
    "tester": ("tester", "testeur"),
    "refill": ("recharge", "refill"),
    "body_product": (
        "gel douche",
        "shower gel",
        "lait corps",
        "body lotion",
        "body mist",
        "hair mist",
        "hair perfume",
        "parfum cheveux",
        "deodorant",
        "diffuseur",
        "bougie",
        "candle",
    ),
    "home_fragrance": (
        "parfum d'ambiance",
        "parfum d ambiance",
        "diffuseur de parfum",
        "brule parfum",
        "room spray",
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", value.replace("×", "x"))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9%.,/+x\s-]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _parse_decimal(text: str) -> float | None:
    cleaned = re.sub(r"[^0-9,.\-]", "", text.replace("\xa0", "").replace(" ", ""))
    if not re.search(r"\d", cleaned):
        return None

    separator_indexes = [index for index, char in enumerate(cleaned) if char in ",."]
    if separator_indexes:
        last_separator = separator_indexes[-1]
        decimal_places = len(cleaned) - last_separator - 1
        if 0 < decimal_places <= 2:
            integer_part = re.sub(r"[,.]", "", cleaned[:last_separator]) or "0"
            decimal_part = re.sub(r"[,.]", "", cleaned[last_separator + 1 :])
            normalized = f"{integer_part}.{decimal_part}"
        else:
            normalized = re.sub(r"[,.]", "", cleaned)
    else:
        normalized = cleaned

    try:
        return float(normalized)
    except ValueError:
        return None


def parse_price(*values: str | None) -> float | None:
    for value in values:
        if not value:
            continue
        parsed = _parse_decimal(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _convert_to_ml(amount: float, unit: str) -> float:
    if unit == "ml":
        return amount
    if unit == "cl":
        return amount * 10
    if unit == "l":
        return amount * 1000
    return amount


def parse_volume_ml(product_name: str | None, description: str | None = None) -> float | None:
    text = normalize_text(" ".join(part for part in (product_name, description) if part))
    if not text:
        return None

    direct_multipack = re.search(r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b", text)
    if direct_multipack:
        multiplier = _parse_decimal(direct_multipack.group(1))
        amount = _parse_decimal(direct_multipack.group(2))
        unit = direct_multipack.group(3)
        if multiplier is not None and amount is not None:
            return round(multiplier * _convert_to_ml(amount, unit), 2)

    reversed_multipack = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\s*x\s*(\d+(?:[.,]\d+)?)\b", text)
    if reversed_multipack:
        amount = _parse_decimal(reversed_multipack.group(1))
        unit = reversed_multipack.group(2)
        multiplier = _parse_decimal(reversed_multipack.group(3))
        if multiplier is not None and amount is not None:
            return round(multiplier * _convert_to_ml(amount, unit), 2)

    volumes: list[float] = []
    for amount_text, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b", text):
        amount = _parse_decimal(amount_text)
        if amount is not None:
            volumes.append(_convert_to_ml(amount, unit))

    return round(max(volumes), 2) if volumes else None


def parse_concentration(product_name: str | None, description: str | None = None) -> str | None:
    text = normalize_text(" ".join(part for part in (product_name, description) if part))
    if not text:
        return None

    for pattern, value in CONCENTRATION_PATTERNS:
        if re.search(pattern, text):
            return value
    return None


def detect_exclusion_reasons(
    product_name: str | None,
    description: str | None = None,
) -> set[str]:
    text = normalize_text(" ".join(part for part in (product_name, description) if part))
    reasons: set[str] = set()
    if not text:
        return reasons

    for reason, keywords in EXCLUSION_KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                reasons.add(reason)
                break
    return reasons


def calculate_coverage_percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100, 1)


def coverage_level(percent: float) -> str:
    if percent >= 80:
        return "high"
    if percent >= 50:
        return "medium"
    return "low"


def count_categories(rows: list[dict[str, str]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        category_name = (row.get("category_name") or "").strip() or "<missing>"
        counter[category_name] += 1
    return dict(sorted(counter.items()))


def _is_non_empty(value: str | None) -> bool:
    return bool(value and value.strip())


def normalize_category(category_name: str | None, merchant_category: str | None = None) -> str:
    primary = normalize_text(category_name)
    if primary:
        return primary
    return normalize_text(merchant_category)


def is_fragrance_category(category_name: str | None, merchant_category: str | None = None) -> bool:
    normalized_category = normalize_category(category_name, merchant_category)
    if any(phrase in normalized_category for phrase in FRAGRANCE_CATEGORY_EXCLUDED_PHRASES):
        return False
    if normalized_category in FRAGRANCE_CATEGORY_ALIASES:
        return True

    tokens = set(normalized_category.split())
    return bool(tokens & FRAGRANCE_CATEGORY_ALIASES)


def _read_csv_payload(
    payload: bytes,
    delimiter_hint: str | None = None,
) -> tuple[list[str], list[dict[str, str]], str, str]:
    if payload.startswith(GZIP_MAGIC):
        decompressed = gzip.decompress(payload)
        compression = "gzip"
    else:
        decompressed = payload
        compression = "plain"

    text = decompressed.decode("utf-8-sig", errors="replace")
    delimiter = delimiter_hint or ","
    if not delimiter_hint:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise AwinCommandError("Feed is empty and has no CSV header")

    header = [field.strip() for field in reader.fieldnames]
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        row: dict[str, str] = {}
        for raw_key, raw_value in raw_row.items():
            if raw_key is None:
                continue
            row[raw_key.strip()] = (raw_value or "").strip()
        rows.append(row)
    return header, rows, delimiter, compression


@dataclass(frozen=True)
class FeedSource:
    source: str
    payload: bytes
    source_reference: str
    source_file_or_url_redacted: bool
    compression_hint: str | None
    delimiter_hint: str | None
    remote_last_imported: str | None
    feed_found: bool | None
    configured_feed_url_env_var: str | None
    download_url_source: str | None
    feed_list_url: str | None
    advertiser_name: str | None
    feed_name: str | None
    language: str | None
    vertical: str | None
    membership_status: str | None


class FeedPreprocessor:
    def __init__(
        self,
        settings: Settings,
        fetcher: AwinFetcher | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.awin_service = AwinService(settings, fetcher=fetcher, environ=environ)

    def preprocess_feed(
        self,
        advertiser_id: str,
        feed_id: str,
        path: Path | None = None,
    ) -> tuple[dict[str, object], Path]:
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "network": "awin",
            "command": "preprocess-feed",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "database_write_performed": False,
        }

        try:
            source = self._resolve_source(advertiser_id=advertiser_id, feed_id=feed_id, path=path)
            header, rows, delimiter, compression = _read_csv_payload(
                source.payload,
                delimiter_hint=source.delimiter_hint,
            )
            rows = [
                canonicalize_row(
                    row,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )
                for row in rows
            ]
            coverage = compare_columns(
                header,
                advertiser_id=advertiser_id,
                feed_id=feed_id,
            )
            metrics = self._build_metrics(rows)
            decision = self._build_decision(coverage, metrics)

            report.update(
                {
                    "status": "success",
                    "source": source.source,
                    "source_reference": source.source_reference,
                    "source_file_or_url_redacted": source.source_file_or_url_redacted,
                    "compression": source.compression_hint or compression,
                    "format": "csv",
                    "delimiter": source.delimiter_hint or delimiter,
                    "header_count": len(header),
                    "rows_total": len(rows),
                    "remote_last_imported": source.remote_last_imported,
                    "feed_found": source.feed_found,
                    "configured_feed_url_env_var": source.configured_feed_url_env_var,
                    "download_url_source": source.download_url_source,
                    "download_url_redacted": source.source == "local_file"
                    or source.download_url_source is not None,
                    "feed_list_url": source.feed_list_url,
                    "advertiser_name": source.advertiser_name,
                    "feed_name": source.feed_name,
                    "language": source.language,
                    "vertical": source.vertical,
                    "membership_status": source.membership_status,
                    **metrics,
                    "missing_required_columns": coverage["required_columns_missing"],
                    "missing_robust_matching_columns": coverage[
                        "robust_matching_columns_missing"
                    ],
                    "missing_recommended_columns": coverage["recommended_columns_missing"],
                    "decision": decision,
                }
            )
            report_path = write_report(
                self.settings.affiliate_data_dir,
                "awin_preprocess_feed",
                report,
            )
            return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "awin_preprocess_feed_error",
                report,
            )
            if report_path is not None:
                raise AwinCommandError(f"{message}. Report written to {report_path}") from exc
            raise AwinCommandError(message) from exc

    def _resolve_source(
        self,
        advertiser_id: str,
        feed_id: str,
        path: Path | None,
    ) -> FeedSource:
        if path is not None:
            payload = path.read_bytes()
            return FeedSource(
                source="local_file",
                payload=payload,
                source_reference="<redacted>",
                source_file_or_url_redacted=True,
                compression_hint="gzip" if payload.startswith(GZIP_MAGIC) else "plain",
                delimiter_hint=None,
                remote_last_imported=None,
                feed_found=None,
                configured_feed_url_env_var=None,
                download_url_source=None,
                feed_list_url=None,
                advertiser_name=None,
                feed_name=None,
                language=None,
                vertical=None,
                membership_status=None,
            )

        configured_env_var, configured_url = get_configured_feed_url(
            advertiser_id=advertiser_id,
            feed_id=feed_id,
            environ=self.awin_service.environ,
        )
        if configured_url:
            payload = self.awin_service.fetcher(configured_url)
            metadata = parse_download_url_metadata(configured_url)
            return FeedSource(
                source="configured_env",
                payload=payload,
                source_reference=redact_url(configured_url) or "<redacted>",
                source_file_or_url_redacted=True,
                compression_hint=metadata["compression"],
                delimiter_hint=metadata["delimiter"],
                remote_last_imported=None,
                feed_found=True,
                configured_feed_url_env_var=configured_env_var,
                download_url_source="configured_env",
                feed_list_url=None,
                advertiser_name=None,
                feed_name=None,
                language=None,
                vertical=None,
                membership_status=None,
            )

        entries, list_url = self.awin_service.fetch_feed_entries()
        target_feed = find_feed(entries, advertiser_id=advertiser_id, feed_id=feed_id)
        if target_feed is None or not target_feed.download_url:
            raise AwinCommandError(
                f"Feed {feed_id} for advertiser {advertiser_id} was not found in the Awin feed list"
            )

        payload = self.awin_service.fetcher(target_feed.download_url)
        metadata = parse_download_url_metadata(target_feed.download_url)
        return FeedSource(
            source="feed_list",
            payload=payload,
            source_reference=redact_url(target_feed.download_url) or "<redacted>",
            source_file_or_url_redacted=True,
            compression_hint=metadata["compression"],
            delimiter_hint=metadata["delimiter"],
            remote_last_imported=target_feed.last_imported,
            feed_found=True,
            configured_feed_url_env_var=configured_env_var,
            download_url_source="feed_list",
            feed_list_url=list_url,
            advertiser_name=target_feed.advertiser_name,
            feed_name=target_feed.feed_name,
            language=target_feed.language,
            vertical=target_feed.vertical,
            membership_status=target_feed.membership_status,
        )

    def _build_metrics(self, rows: list[dict[str, str]]) -> dict[str, object]:
        category_counts = count_categories(rows)
        rows_total = len(rows)
        rows_fragrance = 0
        rows_with_product_name = 0
        rows_with_affiliate_url = 0
        rows_with_valid_price = 0
        rows_with_brand_name = 0
        rows_with_any_identifier = 0
        rows_with_ean = 0
        rows_with_upc = 0
        rows_with_mpn = 0
        rows_with_gtin = 0
        rows_with_stock_status = 0
        rows_with_delivery_cost = 0
        rows_with_image = 0
        rows_with_category_path = 0
        rows_with_volume_ml = 0
        rows_with_concentration = 0
        rows_excluded_set_or_bundle = 0
        rows_excluded_tester = 0
        rows_excluded_refill = 0
        rows_excluded_body_product = 0
        rows_with_affiliate_url_and_price = 0
        estimated_matchable_rows = 0
        fragrance_with_affiliate_url = 0
        fragrance_with_valid_price = 0
        fragrance_with_brand_name = 0
        fragrance_with_any_identifier = 0
        fragrance_with_stock_status = 0
        fragrance_with_volume_ml = 0
        fragrance_with_concentration = 0
        fragrance_with_affiliate_url_and_price = 0

        for row in rows:
            category_name = row.get("category_name")
            is_fragrance = is_fragrance_category(
                category_name,
                row.get("merchant_category") or row.get("product_type"),
            )
            if is_fragrance:
                rows_fragrance += 1

            has_product_name = _is_non_empty(row.get("product_name"))
            has_affiliate_url = any(_is_non_empty(row.get(field)) for field in AFFILIATE_URL_FIELDS)
            has_valid_price = parse_price(*(row.get(field) for field in PRICE_FIELDS)) is not None
            has_brand_name = _is_non_empty(row.get("brand_name"))
            has_ean = _is_non_empty(row.get("ean"))
            has_upc = _is_non_empty(row.get("upc"))
            has_mpn = _is_non_empty(row.get("mpn"))
            has_gtin = _is_non_empty(row.get("product_GTIN"))
            has_stock_status = any(_is_non_empty(row.get(field)) for field in STOCK_FIELDS)
            has_delivery_cost = _is_non_empty(row.get("delivery_cost"))
            has_image = any(_is_non_empty(row.get(field)) for field in IMAGE_FIELDS)
            has_category_path = any(_is_non_empty(row.get(field)) for field in CATEGORY_PATH_FIELDS)
            volume_ml = parse_volume_ml(row.get("product_name"), row.get("description"))
            concentration = parse_concentration(row.get("product_name"), row.get("description"))
            exclusion_reasons = detect_exclusion_reasons(
                row.get("product_name"),
                row.get("description"),
            )
            has_any_identifier = has_ean or has_upc or has_mpn or has_gtin
            has_offer_url_and_price = has_affiliate_url and has_valid_price

            rows_with_product_name += int(has_product_name)
            rows_with_affiliate_url += int(has_affiliate_url)
            rows_with_valid_price += int(has_valid_price)
            rows_with_brand_name += int(has_brand_name)
            rows_with_ean += int(has_ean)
            rows_with_upc += int(has_upc)
            rows_with_mpn += int(has_mpn)
            rows_with_gtin += int(has_gtin)
            rows_with_any_identifier += int(has_any_identifier)
            rows_with_stock_status += int(has_stock_status)
            rows_with_delivery_cost += int(has_delivery_cost)
            rows_with_image += int(has_image)
            rows_with_category_path += int(has_category_path)
            rows_with_volume_ml += int(volume_ml is not None)
            rows_with_concentration += int(concentration is not None)
            rows_excluded_set_or_bundle += int("set_or_bundle" in exclusion_reasons)
            rows_excluded_tester += int("tester" in exclusion_reasons)
            rows_excluded_refill += int("refill" in exclusion_reasons)
            rows_excluded_body_product += int("body_product" in exclusion_reasons)
            rows_with_affiliate_url_and_price += int(has_offer_url_and_price)

            if is_fragrance:
                fragrance_with_affiliate_url += int(has_affiliate_url)
                fragrance_with_valid_price += int(has_valid_price)
                fragrance_with_brand_name += int(has_brand_name)
                fragrance_with_any_identifier += int(has_any_identifier)
                fragrance_with_stock_status += int(has_stock_status)
                fragrance_with_volume_ml += int(volume_ml is not None)
                fragrance_with_concentration += int(concentration is not None)
                fragrance_with_affiliate_url_and_price += int(has_offer_url_and_price)

            if (
                is_fragrance
                and has_product_name
                and has_affiliate_url
                and has_valid_price
                and has_brand_name
                and (volume_ml is not None or has_any_identifier)
                and not exclusion_reasons
            ):
                estimated_matchable_rows += 1

        denominator = rows_fragrance or rows_total
        return {
            "category_counts": category_counts,
            "rows_fragrance": rows_fragrance,
            "rows_with_product_name": rows_with_product_name,
            "rows_with_affiliate_url": rows_with_affiliate_url,
            "rows_with_valid_price": rows_with_valid_price,
            "rows_with_brand_name": rows_with_brand_name,
            "rows_with_any_identifier": rows_with_any_identifier,
            "rows_with_ean": rows_with_ean,
            "rows_with_upc": rows_with_upc,
            "rows_with_mpn": rows_with_mpn,
            "rows_with_gtin": rows_with_gtin,
            "rows_with_stock_status": rows_with_stock_status,
            "rows_with_delivery_cost": rows_with_delivery_cost,
            "rows_with_image": rows_with_image,
            "rows_with_category_path": rows_with_category_path,
            "rows_with_volume_ml": rows_with_volume_ml,
            "rows_with_concentration": rows_with_concentration,
            "rows_excluded_set_or_bundle": rows_excluded_set_or_bundle,
            "rows_excluded_tester": rows_excluded_tester,
            "rows_excluded_refill": rows_excluded_refill,
            "rows_excluded_body_product": rows_excluded_body_product,
            "rows_with_affiliate_url_and_price": rows_with_affiliate_url_and_price,
            "estimated_matchable_rows": estimated_matchable_rows,
            "brand_name_coverage_percent": calculate_coverage_percent(
                fragrance_with_brand_name,
                denominator,
            ),
            "identifier_coverage_percent": calculate_coverage_percent(
                fragrance_with_any_identifier,
                denominator,
            ),
            "volume_coverage_percent": calculate_coverage_percent(
                fragrance_with_volume_ml,
                denominator,
            ),
            "concentration_coverage_percent": calculate_coverage_percent(
                fragrance_with_concentration,
                denominator,
            ),
            "stock_coverage_percent": calculate_coverage_percent(
                fragrance_with_stock_status,
                denominator,
            ),
            "price_coverage_percent": calculate_coverage_percent(
                fragrance_with_valid_price,
                denominator,
            ),
            "affiliate_url_coverage_percent": calculate_coverage_percent(
                fragrance_with_affiliate_url,
                denominator,
            ),
            "offer_url_price_coverage_percent": calculate_coverage_percent(
                fragrance_with_affiliate_url_and_price,
                denominator,
            ),
        }

    def _build_decision(
        self,
        coverage: dict[str, list[str]],
        metrics: dict[str, object],
    ) -> dict[str, str]:
        brand_percent = float(metrics["brand_name_coverage_percent"])
        identifier_percent = float(metrics["identifier_coverage_percent"])
        volume_percent = float(metrics["volume_coverage_percent"])
        concentration_percent = float(metrics["concentration_coverage_percent"])
        stock_percent = float(metrics["stock_coverage_percent"])
        offer_url_price_percent = float(metrics["offer_url_price_coverage_percent"])

        decision = {
            "brand_name_coverage": coverage_level(brand_percent),
            "identifier_coverage": coverage_level(identifier_percent),
            "volume_parsing_coverage": coverage_level(volume_percent),
            "concentration_parsing_coverage": coverage_level(concentration_percent),
            "stock_coverage": coverage_level(stock_percent),
            "offer_url_price_coverage": coverage_level(offer_url_price_percent),
        }

        if coverage["required_columns_missing"]:
            recommendation = "adjust_awin_columns"
        elif identifier_percent <= 0:
            recommendation = "adjust_awin_columns"
        elif any(
            decision[key] == "low"
            for key in (
                "brand_name_coverage",
                "volume_parsing_coverage",
                "offer_url_price_coverage",
            )
        ):
            recommendation = "manual_mapping_needed"
        else:
            recommendation = "proceed_to_db_staging"

        return {**decision, "recommendation": recommendation}


def format_preprocess_report_summary(report: Mapping[str, object], report_path: Path) -> str:
    lines = [
        f"status={report.get('status')}",
        f"source={report.get('source')}",
        f"rows_total={report.get('rows_total')}",
        f"rows_fragrance={report.get('rows_fragrance')}",
        f"estimated_matchable_rows={report.get('estimated_matchable_rows')}",
        f"missing_required_columns={report.get('missing_required_columns', [])}",
        (
            "missing_robust_matching_columns="
            f"{report.get('missing_robust_matching_columns', [])}"
        ),
        f"report_path={report_path}",
    ]
    return "\n".join(lines)
