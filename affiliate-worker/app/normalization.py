from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from app.awin_feed_mapping import compare_columns
from app.config import Settings
from app.db import DatabaseService, DbCommandError
from app.reporting import try_write_report, write_report

AFFILIATE_URL_FIELDS = ("aw_deep_link", "merchant_deep_link")
IMAGE_URL_FIELDS = (
    "large_image",
    "merchant_image_url",
    "aw_image_url",
    "merchant_thumb_url",
    "alternate_image",
    "alternate_image_two",
    "alternate_image_three",
    "alternate_image_four",
)
IDENTIFIER_FIELDS = ("ean", "product_GTIN", "upc", "mpn")
PRICE_FIELDS = ("search_price", "display_price", "store_price")
FRAGRANCE_CATEGORY_ALIASES = {
    "fragrance",
    "fragrances",
    "parfum",
    "parfums",
    "perfume",
    "perfumes",
}
EXCLUSION_KEYWORDS = {
    "set_or_bundle": ("coffret", "set", "duo", "trio"),
    "tester": ("tester", "testeur"),
    "refill": ("recharge", "refill"),
    "body_product": (
        "gel douche",
        "shower gel",
        "lait corps",
        "body lotion",
        "deodorant",
        "deodorant spray",
    ),
    "home_fragrance": ("diffuseur", "bougie", "candle"),
}
CONCENTRATION_PATTERNS = (
    (r"\bextrait de parfum\b|\bperfume extract\b|\bextrait\b", "extrait"),
    (r"\beau de parfum\b|\bedp\b", "edp"),
    (r"\beau de toilette\b|\bedt\b", "edt"),
    (r"\beau de cologne\b|\bedc\b", "edc"),
    (r"\beau fraiche\b|\beau fraiche\b", "eau_fraiche"),
    (r"\bparfum\b", "parfum"),
)
TRUE_TOKENS = {"1", "true", "yes", "y", "in stock", "available", "disponible"}
FALSE_TOKENS = {"0", "false", "no", "n", "out of stock", "unavailable", "sold out"}
ML_QUANTUM = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.01")
METRIC_UNIT_PATTERN = r"(?:ml|cl|l(?!['a-z]))"


class NormalizationError(RuntimeError):
    """Raised when normalization cannot complete safely."""


@dataclass(frozen=True)
class StockParseResult:
    in_stock: bool | None
    stock_status: str | None


@dataclass(frozen=True)
class NormalizedFeedItem:
    raw_feed_item_id: int
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
    merchant_category: str | None
    price: Decimal | None
    currency: str
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_for_parsing(value: str | None) -> str:
    if not value:
        return ""

    text = html.unescape(value)
    text = text.replace("\xa0", " ")
    text = text.replace("’", "'").replace("`", "'").replace("´", "'")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = text.replace("×", " x ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(value: str | None) -> str:
    text = _normalize_for_parsing(value)
    if not text:
        return ""

    text = re.sub(r"[’'`´]", " ", text)
    text = re.sub(r"[&]", " and ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_currency(value: str | None, default: str = "EUR") -> str:
    if not value or not value.strip():
        return default

    normalized = value.strip().upper()
    if normalized == "€":
        return "EUR"
    if len(normalized) == 3 and normalized.isalpha():
        return normalized
    return default


def _clean_decimal_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^0-9,.\-]", "", html.unescape(value).replace("\xa0", "").replace(" ", ""))


def _parse_decimal(value: str | None) -> Decimal | None:
    cleaned = _clean_decimal_text(value)
    if not cleaned or not re.search(r"\d", cleaned):
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
        return Decimal(normalized)
    except InvalidOperation:
        return None


def parse_price(*values: str | None) -> Decimal | None:
    for value in values:
        parsed = _parse_decimal(value)
        if parsed is not None and parsed > 0:
            return parsed.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
    return None


def _convert_to_ml(amount: Decimal, unit: str) -> Decimal:
    if unit == "ml":
        return amount
    if unit == "cl":
        return amount * Decimal("10")
    if unit == "l":
        return amount * Decimal("1000")
    if unit == "oz":
        return amount * Decimal("29.5735")
    return amount


def parse_volume_ml(product_name: str | None, description: str | None = None) -> Decimal | None:
    text = _normalize_for_parsing(" ".join(part for part in (product_name, description) if part))
    if not text:
        return None

    explicit_patterns = (
        rf"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*({METRIC_UNIT_PATTERN})\b",
        rf"(\d+(?:[.,]\d+)?)\s*({METRIC_UNIT_PATTERN})\s*x\s*(\d+(?:[.,]\d+)?)\b",
    )
    for pattern in explicit_patterns:
        match = re.search(pattern, text)
        if match:
            if "x\\s*" in pattern and pattern.index("x\\s*") < pattern.index(METRIC_UNIT_PATTERN):
                left = _parse_decimal(match.group(1))
                right = _parse_decimal(match.group(2))
                unit = match.group(3)
                if left is not None and right is not None:
                    return (left * _convert_to_ml(right, unit)).quantize(
                        ML_QUANTUM, rounding=ROUND_HALF_UP
                    )
            else:
                amount = _parse_decimal(match.group(1))
                unit = match.group(2)
                multiplier = _parse_decimal(match.group(3))
                if multiplier is not None and amount is not None:
                    return (multiplier * _convert_to_ml(amount, unit)).quantize(
                        ML_QUANTUM, rounding=ROUND_HALF_UP
                    )

    plus_match = re.search(
        rf"(\d+(?:[.,]\d+)?)\s*\+\s*(\d+(?:[.,]\d+)?)\s*({METRIC_UNIT_PATTERN})\b",
        text,
    )
    if plus_match:
        first = _parse_decimal(plus_match.group(1))
        second = _parse_decimal(plus_match.group(2))
        unit = plus_match.group(3)
        if first is not None and second is not None:
            return _convert_to_ml(first + second, unit).quantize(
                ML_QUANTUM, rounding=ROUND_HALF_UP
            )

    metric_candidates: list[Decimal] = []
    for amount_text, unit in re.findall(
        rf"(\d+(?:[.,]\d+)?)\s*({METRIC_UNIT_PATTERN})\b",
        text,
    ):
        amount = _parse_decimal(amount_text)
        if amount is not None:
            metric_candidates.append(_convert_to_ml(amount, unit))
    if metric_candidates:
        return max(metric_candidates).quantize(ML_QUANTUM, rounding=ROUND_HALF_UP)

    imperial_candidates: list[Decimal] = []
    for amount_text, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(oz)\b", text):
        amount = _parse_decimal(amount_text)
        if amount is not None:
            imperial_candidates.append(_convert_to_ml(amount, unit))
    if imperial_candidates:
        return max(imperial_candidates).quantize(ML_QUANTUM, rounding=ROUND_HALF_UP)

    return None


def parse_concentration(product_name: str | None, description: str | None = None) -> str | None:
    text = _normalize_for_parsing(" ".join(part for part in (product_name, description) if part))
    if not text:
        return None

    for pattern, value in CONCENTRATION_PATTERNS:
        if re.search(pattern, text):
            return value
    return None


def detect_exclusion_reasons(*values: str | None) -> list[str]:
    text = " ".join(_normalize_for_parsing(value) for value in values if value)
    reasons: list[str] = []
    if not text:
        return reasons

    for reason, keywords in EXCLUSION_KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                reasons.append(reason)
                break
    return reasons


def parse_stock(
    in_stock_value: str | None,
    stock_status_value: str | None,
    stock_quantity_value: str | None,
) -> StockParseResult:
    stock_status = (stock_status_value or "").strip() or None
    in_stock_text = _normalize_for_parsing(in_stock_value)
    stock_status_text = _normalize_for_parsing(stock_status_value)
    quantity = _parse_decimal(stock_quantity_value)

    if in_stock_text in TRUE_TOKENS:
        return StockParseResult(True, stock_status)
    if in_stock_text in FALSE_TOKENS:
        return StockParseResult(False, stock_status)
    if stock_status_text in TRUE_TOKENS:
        return StockParseResult(True, stock_status)
    if stock_status_text in FALSE_TOKENS:
        return StockParseResult(False, stock_status)
    if quantity is not None:
        return StockParseResult(quantity > 0, stock_status)
    return StockParseResult(None, stock_status)


def select_affiliate_url(row: Mapping[str, str]) -> str | None:
    for field in AFFILIATE_URL_FIELDS:
        value = (row.get(field) or "").strip()
        if value:
            return value
    return None


def select_merchant_url(row: Mapping[str, str]) -> str | None:
    value = (row.get("merchant_deep_link") or "").strip()
    return value or None


def select_image_url(row: Mapping[str, str]) -> str | None:
    for field in IMAGE_URL_FIELDS:
        value = (row.get(field) or "").strip()
        if value:
            return value
    return None


def clean_identifier(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def extract_brand_fallback(product_name: str | None) -> str | None:
    if not product_name or not product_name.strip():
        return None

    text = html.unescape(product_name).strip()
    for separator in (" - ", " – ", " — ", ": "):
        if separator not in text:
            continue
        candidate = text.split(separator, 1)[0].strip()
        tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9'&.-]+", candidate)
        if 1 <= len(tokens) <= 3 and all(token[0].isupper() for token in tokens if token):
            return candidate
    return None


def normalize_category(category_name: str | None, merchant_category: str | None = None) -> str:
    primary = normalize_text(category_name)
    if primary:
        return primary
    return normalize_text(merchant_category)


def is_fragrance_category(category_name: str | None, merchant_category: str | None = None) -> bool:
    normalized_category = normalize_category(category_name, merchant_category)
    if normalized_category in FRAGRANCE_CATEGORY_ALIASES:
        return True

    tokens = set(normalized_category.split())
    return bool(tokens & FRAGRANCE_CATEGORY_ALIASES)


def calculate_coverage_percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100, 1)


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class NormalizationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_service = DatabaseService(settings)

    def normalize_feed(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
        import_run_id: int | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, object], Path]:
        self.db_service.require_database_url()
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "normalize-feed",
            "network": "awin",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "dry_run": dry_run,
            "source": "raw_feed_items",
            "database_url_redacted": True,
            "selection_limit": limit,
        }

        try:
            with self.db_service.connect() as conn:
                advertiser_row, affiliate_feed_row = self._resolve_feed_context(
                    conn,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )
                selected_import_run_id, raw_rows_available = self._select_source_import_run(
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                    import_run_id=import_run_id,
                )
                raw_rows = self._load_raw_rows(
                    conn,
                    advertiser_db_id=int(advertiser_row["id"]),
                    import_run_id=selected_import_run_id,
                    limit=limit,
                )
                if not raw_rows:
                    raise NormalizationError(
                        f"No raw_feed_items found for import_run_id={selected_import_run_id}."
                    )

                header_columns = sorted(
                    {
                        str(key)
                        for row in raw_rows
                        for key in dict(row["raw_payload"]).keys()
                    }
                )
                column_report = compare_columns(header_columns)
                normalized_rows = [
                    self._normalize_row(
                        raw_row,
                        advertiser_db_id=int(advertiser_row["id"]),
                        affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                        missing_required_columns=column_report["required_columns_missing"],
                        missing_recommended_columns=column_report[
                            "recommended_columns_missing"
                        ],
                    )
                    for raw_row in raw_rows
                ]

                metrics = self._build_metrics(normalized_rows)
                report.update(
                    {
                        "status": "success",
                        "import_run_id": selected_import_run_id,
                        "raw_rows_total": len(raw_rows),
                        "raw_rows_available": raw_rows_available,
                        "header_count": len(header_columns),
                        "normalized_rows_inserted": 0,
                        "normalized_rows_updated": 0,
                        "normalized_rows_duplicates": 0,
                        "advertiser_db_id": advertiser_row["id"],
                        "affiliate_feed_db_id": affiliate_feed_row["id"],
                        "missing_required_columns": column_report["required_columns_missing"],
                        "missing_recommended_columns": column_report[
                            "recommended_columns_missing"
                        ],
                        "missing_robust_matching_columns": column_report[
                            "robust_matching_columns_missing"
                        ],
                        **metrics,
                    }
                )

                if not dry_run:
                    inserted, updated, duplicates = self._persist_normalized_rows(
                        conn,
                        normalized_rows,
                    )
                    report["normalized_rows_inserted"] = inserted
                    report["normalized_rows_updated"] = updated
                    report["normalized_rows_duplicates"] = duplicates

                report_path = write_report(
                    self.settings.affiliate_data_dir,
                    "normalize_feed",
                    report,
                )
                return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "normalize_feed_error",
                report,
            )
            if report_path is not None:
                raise NormalizationError(f"{message}. Report written to {report_path}") from exc
            raise NormalizationError(message) from exc

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
                "Run migrate-db from PR04/PR05/PR06 first."
            )

        affiliate_feed_row = conn.execute(
            """
            select id, advertiser_id, network, network_feed_id
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
                "Run migrate-db from PR04/PR05/PR06 first."
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
        import_run_id: int | None,
    ) -> tuple[int, int]:
        if import_run_id is not None:
            row = conn.execute(
                """
                select
                    fir.id,
                    count(rfi.id)::integer as raw_rows_total
                from feed_import_runs fir
                left join raw_feed_items rfi
                  on rfi.import_run_id = fir.id
                 and rfi.advertiser_id = %s
                where fir.id = %s
                  and fir.feed_id = %s
                  and fir.status = 'success'
                group by fir.id
                """,
                (advertiser_db_id, import_run_id, affiliate_feed_db_id),
            ).fetchone()
            if row is None:
                raise NormalizationError(
                    "Import run "
                    f"{import_run_id} is not a successful run for feed "
                    f"{affiliate_feed_db_id}."
                )
            return int(row["id"]), int(row["raw_rows_total"] or 0)

        row = conn.execute(
            """
            select
                fir.id,
                count(rfi.id)::integer as raw_rows_total
            from feed_import_runs fir
            join raw_feed_items rfi
              on rfi.import_run_id = fir.id
             and rfi.advertiser_id = %s
            where fir.feed_id = %s
              and fir.status = 'success'
            group by fir.id
            order by fir.id desc
            limit 1
            """,
            (advertiser_db_id, affiliate_feed_db_id),
        ).fetchone()
        if row is None:
            raise NormalizationError(
                "No successful raw staging import with persisted rows was found for this feed."
            )
        return int(row["id"]), int(row["raw_rows_total"] or 0)

    def _load_raw_rows(
        self,
        conn: Any,
        *,
        advertiser_db_id: int,
        import_run_id: int,
        limit: int | None,
    ) -> list[dict[str, object]]:
        sql = """
            select
                id as raw_feed_item_id,
                network,
                network_product_id,
                merchant_product_id,
                raw_payload
            from raw_feed_items
            where advertiser_id = %s
              and import_run_id = %s
            order by id
        """
        params: list[object] = [advertiser_db_id, import_run_id]
        if limit is not None:
            sql += " limit %s"
            params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def _normalize_row(
        self,
        raw_row: Mapping[str, object],
        *,
        advertiser_db_id: int,
        affiliate_feed_db_id: int,
        missing_required_columns: list[str],
        missing_recommended_columns: list[str],
    ) -> NormalizedFeedItem:
        payload = {
            str(key): str(value) if value is not None else ""
            for key, value in dict(raw_row["raw_payload"]).items()
        }

        title = (payload.get("product_name") or "").strip()
        description = (payload.get("description") or "").strip() or None
        brand = (payload.get("brand_name") or "").strip() or extract_brand_fallback(title)
        normalized_brand = normalize_text(brand) or None
        category = (payload.get("category_name") or "").strip() or None
        merchant_category = (payload.get("merchant_category") or "").strip() or None
        normalized_category = normalize_category(category, merchant_category) or None
        is_fragrance = is_fragrance_category(category, merchant_category)
        exclusion_reasons = detect_exclusion_reasons(
            title,
            description,
            merchant_category,
            payload.get("product_type"),
            payload.get("keywords"),
            payload.get("specifications"),
        )
        is_excluded = bool(exclusion_reasons)

        price = parse_price(*(payload.get(field) for field in PRICE_FIELDS))
        delivery_cost = parse_price(payload.get("delivery_cost"))
        currency = normalize_currency(payload.get("currency"))
        affiliate_url = select_affiliate_url(payload)
        merchant_url = select_merchant_url(payload)
        image_url = select_image_url(payload)
        ean = clean_identifier(payload.get("ean"))
        gtin = clean_identifier(payload.get("product_GTIN"))
        upc = clean_identifier(payload.get("upc"))
        mpn = clean_identifier(payload.get("mpn"))
        stock = parse_stock(
            payload.get("in_stock"),
            payload.get("stock_status"),
            payload.get("stock_quantity"),
        )
        concentration = parse_concentration(title, description)
        volume_ml = parse_volume_ml(title, description)

        normalized_payload: dict[str, object] = {
            "title": title,
            "normalized_title": normalize_text(title),
            "description": description,
            "brand": brand,
            "normalized_brand": normalized_brand,
            "category": category,
            "normalized_category": normalized_category,
            "merchant_category": merchant_category,
            "price": _decimal_to_string(price),
            "currency": currency,
            "delivery_cost": _decimal_to_string(delivery_cost),
            "affiliate_url": affiliate_url,
            "merchant_url": merchant_url,
            "image_url": image_url,
            "ean": ean,
            "gtin": gtin,
            "upc": upc,
            "mpn": mpn,
            "in_stock": stock.in_stock,
            "stock_status": stock.stock_status,
            "concentration": concentration,
            "volume_ml": _decimal_to_string(volume_ml),
            "is_fragrance": is_fragrance,
            "is_excluded": is_excluded,
            "exclusion_reasons": exclusion_reasons,
            "missing_required_columns": missing_required_columns,
            "missing_recommended_columns": missing_recommended_columns,
        }

        network_product_id = (
            str(raw_row["network_product_id"])
            if raw_row["network_product_id"] is not None
            else None
        )
        merchant_product_id = (
            str(raw_row["merchant_product_id"])
            if raw_row["merchant_product_id"] is not None
            else None
        )

        return NormalizedFeedItem(
            raw_feed_item_id=int(raw_row["raw_feed_item_id"]),
            advertiser_id=advertiser_db_id,
            feed_id=affiliate_feed_db_id,
            network=str(raw_row["network"]),
            network_product_id=clean_identifier(network_product_id),
            merchant_product_id=clean_identifier(merchant_product_id),
            title=title,
            normalized_title=normalize_text(title),
            description=description,
            brand=brand,
            normalized_brand=normalized_brand,
            category=category,
            normalized_category=normalized_category,
            merchant_category=merchant_category,
            price=price,
            currency=currency,
            delivery_cost=delivery_cost,
            affiliate_url=affiliate_url,
            merchant_url=merchant_url,
            image_url=image_url,
            ean=ean,
            gtin=gtin,
            upc=upc,
            mpn=mpn,
            in_stock=stock.in_stock,
            stock_status=stock.stock_status,
            concentration=concentration,
            volume_ml=volume_ml,
            is_fragrance=is_fragrance,
            is_excluded=is_excluded,
            exclusion_reasons=exclusion_reasons,
            missing_required_columns=missing_required_columns,
            missing_recommended_columns=missing_recommended_columns,
            normalized_payload=normalized_payload,
        )

    def _persist_normalized_rows(
        self,
        conn: Any,
        normalized_rows: list[NormalizedFeedItem],
    ) -> tuple[int, int, int]:
        inserted = 0
        updated = 0
        duplicates = 0

        with conn.transaction():
            for item in normalized_rows:
                existing_row = conn.execute(
                    """
                    select normalized_payload
                    from normalized_feed_items
                    where raw_feed_item_id = %s
                    """,
                    (item.raw_feed_item_id,),
                ).fetchone()

                if existing_row is None:
                    conn.execute(
                        """
                        insert into normalized_feed_items (
                            raw_feed_item_id,
                            advertiser_id,
                            feed_id,
                            network,
                            network_product_id,
                            merchant_product_id,
                            title,
                            normalized_title,
                            description,
                            brand,
                            normalized_brand,
                            category,
                            normalized_category,
                            merchant_category,
                            price,
                            currency,
                            delivery_cost,
                            affiliate_url,
                            merchant_url,
                            image_url,
                            ean,
                            gtin,
                            upc,
                            mpn,
                            in_stock,
                            stock_status,
                            concentration,
                            volume_ml,
                            is_fragrance,
                            is_excluded,
                            exclusion_reasons,
                            missing_required_columns,
                            missing_recommended_columns,
                            normalized_payload
                        )
                        values (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s
                        )
                        """,
                        self._db_values(item),
                    )
                    inserted += 1
                    continue

                existing_payload = dict(existing_row["normalized_payload"])
                if _canonical_json(existing_payload) == _canonical_json(item.normalized_payload):
                    duplicates += 1
                    continue

                conn.execute(
                    """
                    update normalized_feed_items
                    set advertiser_id = %s,
                        feed_id = %s,
                        network = %s,
                        network_product_id = %s,
                        merchant_product_id = %s,
                        title = %s,
                        normalized_title = %s,
                        description = %s,
                        brand = %s,
                        normalized_brand = %s,
                        category = %s,
                        normalized_category = %s,
                        merchant_category = %s,
                        price = %s,
                        currency = %s,
                        delivery_cost = %s,
                        affiliate_url = %s,
                        merchant_url = %s,
                        image_url = %s,
                        ean = %s,
                        gtin = %s,
                        upc = %s,
                        mpn = %s,
                        in_stock = %s,
                        stock_status = %s,
                        concentration = %s,
                        volume_ml = %s,
                        is_fragrance = %s,
                        is_excluded = %s,
                        exclusion_reasons = %s,
                        missing_required_columns = %s,
                        missing_recommended_columns = %s,
                        normalized_payload = %s,
                        updated_at = now()
                    where raw_feed_item_id = %s
                    """,
                    self._db_values(item)[1:] + (
                        item.raw_feed_item_id,
                    ),
                )
                updated += 1

        return inserted, updated, duplicates

    def _db_values(self, item: NormalizedFeedItem) -> tuple[object, ...]:
        return (
            item.raw_feed_item_id,
            item.advertiser_id,
            item.feed_id,
            item.network,
            item.network_product_id,
            item.merchant_product_id,
            item.title,
            item.normalized_title,
            item.description,
            item.brand,
            item.normalized_brand,
            item.category,
            item.normalized_category,
            item.merchant_category,
            item.price,
            item.currency,
            item.delivery_cost,
            item.affiliate_url,
            item.merchant_url,
            item.image_url,
            item.ean,
            item.gtin,
            item.upc,
            item.mpn,
            item.in_stock,
            item.stock_status,
            item.concentration,
            item.volume_ml,
            item.is_fragrance,
            item.is_excluded,
            Jsonb(item.exclusion_reasons),
            Jsonb(item.missing_required_columns),
            Jsonb(item.missing_recommended_columns),
            Jsonb(item.normalized_payload),
        )

    def _build_metrics(self, normalized_rows: list[NormalizedFeedItem]) -> dict[str, object]:
        total = len(normalized_rows)
        rows_fragrance = sum(1 for row in normalized_rows if row.is_fragrance)
        rows_excluded = sum(1 for row in normalized_rows if row.is_excluded)
        rows_excluded_by_reason: dict[str, int] = {}
        for reason in EXCLUSION_KEYWORDS:
            rows_excluded_by_reason[reason] = sum(
                1 for row in normalized_rows if reason in row.exclusion_reasons
            )

        rows_with_brand = sum(1 for row in normalized_rows if row.brand)
        rows_with_ean = sum(1 for row in normalized_rows if row.ean)
        rows_with_gtin = sum(1 for row in normalized_rows if row.gtin)
        rows_with_upc = sum(1 for row in normalized_rows if row.upc)
        rows_with_mpn = sum(1 for row in normalized_rows if row.mpn)
        rows_with_any_identifier = sum(
            1 for row in normalized_rows if row.ean or row.gtin or row.upc or row.mpn
        )
        rows_with_volume_ml = sum(1 for row in normalized_rows if row.volume_ml is not None)
        rows_with_concentration = sum(1 for row in normalized_rows if row.concentration)
        rows_with_price = sum(1 for row in normalized_rows if row.price is not None)
        rows_with_affiliate_url = sum(1 for row in normalized_rows if row.affiliate_url)
        rows_with_image_url = sum(1 for row in normalized_rows if row.image_url)
        rows_actionable_fragrance = sum(
            1
            for row in normalized_rows
            if row.is_fragrance
            and not row.is_excluded
            and row.title
            and row.affiliate_url
            and row.price is not None
            and row.brand
            and (row.volume_ml is not None or row.ean or row.gtin or row.upc or row.mpn)
        )

        return {
            "rows_fragrance": rows_fragrance,
            "rows_actionable_fragrance": rows_actionable_fragrance,
            "rows_excluded": rows_excluded,
            "rows_excluded_set_or_bundle": rows_excluded_by_reason["set_or_bundle"],
            "rows_excluded_tester": rows_excluded_by_reason["tester"],
            "rows_excluded_refill": rows_excluded_by_reason["refill"],
            "rows_excluded_body_product": rows_excluded_by_reason["body_product"],
            "rows_excluded_home_fragrance": rows_excluded_by_reason["home_fragrance"],
            "rows_with_brand": rows_with_brand,
            "rows_with_any_identifier": rows_with_any_identifier,
            "rows_with_ean": rows_with_ean,
            "rows_with_gtin": rows_with_gtin,
            "rows_with_upc": rows_with_upc,
            "rows_with_mpn": rows_with_mpn,
            "rows_with_volume_ml": rows_with_volume_ml,
            "rows_with_concentration": rows_with_concentration,
            "rows_with_price": rows_with_price,
            "rows_with_affiliate_url": rows_with_affiliate_url,
            "rows_with_image_url": rows_with_image_url,
            "brand_coverage_percent": calculate_coverage_percent(rows_with_brand, total),
            "identifier_coverage_percent": calculate_coverage_percent(
                rows_with_any_identifier,
                total,
            ),
            "volume_coverage_percent": calculate_coverage_percent(rows_with_volume_ml, total),
            "concentration_coverage_percent": calculate_coverage_percent(
                rows_with_concentration,
                total,
            ),
            "price_coverage_percent": calculate_coverage_percent(rows_with_price, total),
            "affiliate_url_coverage_percent": calculate_coverage_percent(
                rows_with_affiliate_url,
                total,
            ),
            "image_url_coverage_percent": calculate_coverage_percent(
                rows_with_image_url,
                total,
            ),
        }


def format_normalization_report_summary(report: Mapping[str, object], report_path: Path) -> str:
    lines = [
        f"status={report.get('status')}",
        f"network={report.get('network')}",
        f"source={report.get('source')}",
        f"dry_run={report.get('dry_run')}",
        f"import_run_id={report.get('import_run_id')}",
        f"raw_rows_total={report.get('raw_rows_total')}",
        f"normalized_rows_inserted={report.get('normalized_rows_inserted')}",
        f"normalized_rows_updated={report.get('normalized_rows_updated')}",
        f"normalized_rows_duplicates={report.get('normalized_rows_duplicates')}",
        f"rows_fragrance={report.get('rows_fragrance')}",
        f"rows_actionable_fragrance={report.get('rows_actionable_fragrance')}",
        f"rows_excluded={report.get('rows_excluded')}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)
