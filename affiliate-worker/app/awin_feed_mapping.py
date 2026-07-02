from __future__ import annotations

from typing import Mapping

"""Column expectations derived from docs/prd/affiliate-system/20_data/awin_feed_mapping.md."""

REQUIRED_COLUMNS = [
    "aw_product_id",
    "merchant_product_id",
    "product_name",
    "aw_deep_link",
    "merchant_image_url",
    "description",
    "merchant_category",
    "search_price",
    "merchant_name",
    "merchant_id",
    "category_name",
    "category_id",
    "currency",
    "display_price",
    "data_feed_id",
]

ROBUST_MATCHING_COLUMNS = [
    "brand_name",
    "brand_id",
    "ean",
    "upc",
    "mpn",
    "product_GTIN",
    "parent_product_id",
    "merchant_product_category_path",
    "merchant_product_second_category",
    "merchant_product_third_category",
    "product_type",
    "keywords",
    "specifications",
    "in_stock",
    "stock_quantity",
    "stock_status",
    "is_for_sale",
    "web_offer",
    "pre_order",
    "valid_from",
    "valid_to",
    "delivery_cost",
    "delivery_time",
    "large_image",
    "merchant_thumb_url",
    "alternate_image",
    "alternate_image_two",
    "alternate_image_three",
    "alternate_image_four",
    "commission_group",
]

RECOMMENDED_COLUMNS = [
    "aw_deep_link",
    "product_name",
    "aw_product_id",
    "merchant_product_id",
    "merchant_image_url",
    "description",
    "merchant_category",
    "search_price",
    "merchant_name",
    "merchant_id",
    "category_name",
    "category_id",
    "aw_image_url",
    "currency",
    "store_price",
    "delivery_cost",
    "merchant_deep_link",
    "language",
    "last_updated",
    "display_price",
    "data_feed_id",
    "brand_name",
    "brand_id",
    "colour",
    "product_short_description",
    "specifications",
    "condition",
    "product_model",
    "model_number",
    "dimensions",
    "keywords",
    "product_type",
    "commission_group",
    "merchant_product_category_path",
    "merchant_product_second_category",
    "merchant_product_third_category",
    "rrp_price",
    "saving",
    "savings_percent",
    "base_price",
    "base_price_amount",
    "base_price_text",
    "product_price_old",
    "delivery_restrictions",
    "delivery_weight",
    "warranty",
    "terms_of_contract",
    "delivery_time",
    "in_stock",
    "stock_quantity",
    "valid_from",
    "valid_to",
    "is_for_sale",
    "web_offer",
    "pre_order",
    "stock_status",
    "size_stock_status",
    "size_stock_amount",
    "merchant_thumb_url",
    "large_image",
    "alternate_image",
    "aw_thumb_url",
    "alternate_image_two",
    "alternate_image_three",
    "alternate_image_four",
    "reviews",
    "average_rating",
    "rating",
    "number_available",
    "custom_1",
    "custom_2",
    "custom_3",
    "custom_4",
    "custom_5",
    "custom_6",
    "custom_7",
    "custom_8",
    "custom_9",
    "ean",
    "isbn",
    "upc",
    "mpn",
    "parent_product_id",
    "product_GTIN",
    "basket_link",
]

FLACONI_FR_PROFILE_KEY = ("87361", "97463")

PROFILE_DERIVED_COLUMNS: dict[tuple[str, str], dict[str, tuple[str, ...]]] = {
    FLACONI_FR_PROFILE_KEY: {
        "display_price": ("search_price", "rrp_price", "store_price"),
        "category_name": ("merchant_category", "product_type"),
        "product_GTIN": ("ean",),
        "large_image": ("merchant_image_url", "aw_image_url"),
        "merchant_thumb_url": ("aw_thumb_url", "merchant_image_url"),
    }
}


def profile_name(advertiser_id: str | None = None, feed_id: str | None = None) -> str:
    if (str(advertiser_id or ""), str(feed_id or "")) == FLACONI_FR_PROFILE_KEY:
        return "flaconi_fr"
    return "default"


def _derived_columns_for(
    advertiser_id: str | None = None,
    feed_id: str | None = None,
) -> dict[str, tuple[str, ...]]:
    return PROFILE_DERIVED_COLUMNS.get(
        (str(advertiser_id or ""), str(feed_id or "")),
        {},
    )


def _is_usable_value(target_column: str, value: str | None) -> bool:
    if value is None:
        return False

    normalized = value.strip()
    if not normalized:
        return False

    if target_column in {"display_price", "search_price", "store_price", "rrp_price"}:
        return normalized.lower() not in {"false", "n/a", "null"}

    return True


def canonicalize_header(
    header: list[str],
    *,
    advertiser_id: str | None = None,
    feed_id: str | None = None,
) -> list[str]:
    canonical = [column.strip() for column in header if column and column.strip()]
    canonical_set = set(canonical)
    for target_column, source_columns in _derived_columns_for(advertiser_id, feed_id).items():
        if target_column in canonical_set:
            continue
        if any(source_column in canonical_set for source_column in source_columns):
            canonical.append(target_column)
            canonical_set.add(target_column)
    return canonical


def canonicalize_row(
    row: Mapping[str, str],
    *,
    advertiser_id: str | None = None,
    feed_id: str | None = None,
) -> dict[str, str]:
    canonical = {
        str(key).strip(): (value if value is not None else "")
        for key, value in row.items()
        if key is not None and str(key).strip()
    }

    for target_column, source_columns in _derived_columns_for(advertiser_id, feed_id).items():
        if _is_usable_value(target_column, canonical.get(target_column)):
            continue
        for source_column in source_columns:
            value = canonical.get(source_column)
            if _is_usable_value(target_column, value):
                canonical[target_column] = value
                break

    return canonical


def compare_columns(
    header: list[str],
    *,
    advertiser_id: str | None = None,
    feed_id: str | None = None,
) -> dict[str, list[str]]:
    header_set = set(
        canonicalize_header(
            header,
            advertiser_id=advertiser_id,
            feed_id=feed_id,
        )
    )
    return {
        "required_columns_present": [
            column for column in REQUIRED_COLUMNS if column in header_set
        ],
        "required_columns_missing": [
            column for column in REQUIRED_COLUMNS if column not in header_set
        ],
        "robust_matching_columns_present": [
            column for column in ROBUST_MATCHING_COLUMNS if column in header_set
        ],
        "robust_matching_columns_missing": [
            column for column in ROBUST_MATCHING_COLUMNS if column not in header_set
        ],
        "recommended_columns_present": [
            column for column in RECOMMENDED_COLUMNS if column in header_set
        ],
        "recommended_columns_missing": [
            column for column in RECOMMENDED_COLUMNS if column not in header_set
        ],
    }
