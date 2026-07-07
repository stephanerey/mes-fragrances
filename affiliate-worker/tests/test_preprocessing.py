from __future__ import annotations

import csv
import gzip
import json
from io import StringIO
from pathlib import Path

import pytest

from app.awin import AwinCommandError, build_feed_list_url
from app.config import Settings
from app.preprocessing import (
    FeedPreprocessor,
    calculate_coverage_percent,
    count_categories,
    detect_exclusion_reasons,
    normalize_text,
    parse_concentration,
    parse_price,
    parse_volume_ml,
)

CONFIGURED_DOWNLOAD_URL = (
    "https://productdata.awin.com/datafeed/download/apikey/secret-feed-key/fid/97867/"
    "format/csv/language/fr/delimiter/%2C/compression/gzip"
)
FEED_LIST_CSV = "\n".join(
    [
        "Advertiser ID,Advertiser Name,Primary Region,Membership Status,Feed ID,"
        "Feed Name,Language,Vertical,Last Imported,URL",
        "105475,Perfumerias Comas FR,FR,Joined,97867,Perfumerias Comas FR PDF,"
        f"fr_FR,Retail,2026-05-21 12:00:00,{CONFIGURED_DOWNLOAD_URL}",
    ]
) + "\n"
HEADER = [
    "aw_product_id",
    "merchant_product_id",
    "product_name",
    "aw_deep_link",
    "merchant_deep_link",
    "merchant_image_url",
    "aw_image_url",
    "description",
    "merchant_category",
    "search_price",
    "store_price",
    "merchant_name",
    "merchant_id",
    "category_name",
    "category_id",
    "currency",
    "display_price",
    "data_feed_id",
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
ROWS = [
    {
        "aw_product_id": "1",
        "merchant_product_id": "SKU-1",
        "product_name": "Lancome La Vie Est Belle Eau de Parfum 50 ml",
        "aw_deep_link": "https://example.test/deep-link-1",
        "merchant_deep_link": "",
        "merchant_image_url": "https://example.test/image-1.jpg",
        "aw_image_url": "https://example.test/aw-image-1.jpg",
        "description": "Floral fragrance with 50 ml bottle.",
        "merchant_category": "Fragrance",
        "search_price": "99.90",
        "store_price": "",
        "merchant_name": "Comas",
        "merchant_id": "105475",
        "category_name": "Fragrance",
        "category_id": "12",
        "currency": "EUR",
        "display_price": "99,90 EUR",
        "data_feed_id": "97867",
        "brand_name": "Lancome",
        "brand_id": "LAN",
        "ean": "1234567890123",
        "upc": "",
        "mpn": "",
        "product_GTIN": "1234567890123",
        "parent_product_id": "PARENT-1",
        "merchant_product_category_path": "Fragrance > Women",
        "merchant_product_second_category": "Women",
        "merchant_product_third_category": "Eau de Parfum",
        "product_type": "Perfume",
        "keywords": "fragrance floral",
        "specifications": "spray bottle",
        "in_stock": "1",
        "stock_quantity": "7",
        "stock_status": "in stock",
        "is_for_sale": "1",
        "web_offer": "0",
        "pre_order": "0",
        "valid_from": "2026-05-21",
        "valid_to": "2026-06-21",
        "delivery_cost": "0",
        "delivery_time": "48h",
        "large_image": "https://example.test/large-1.jpg",
        "merchant_thumb_url": "https://example.test/thumb-1.jpg",
        "alternate_image": "https://example.test/alt-1.jpg",
        "alternate_image_two": "",
        "alternate_image_three": "",
        "alternate_image_four": "",
        "commission_group": "default",
    },
    {
        "aw_product_id": "2",
        "merchant_product_id": "SKU-2",
        "product_name": "Dior Sauvage Coffret EDT 2 x 50 ml",
        "aw_deep_link": "",
        "merchant_deep_link": "https://example.test/deep-link-2",
        "merchant_image_url": "https://example.test/image-2.jpg",
        "aw_image_url": "",
        "description": "Gift set with two bottles.",
        "merchant_category": "Fragrance",
        "search_price": "",
        "store_price": "",
        "merchant_name": "Comas",
        "merchant_id": "105475",
        "category_name": "Fragrance",
        "category_id": "12",
        "currency": "EUR",
        "display_price": "129,99 EUR",
        "data_feed_id": "97867",
        "brand_name": "Dior",
        "brand_id": "DIOR",
        "ean": "",
        "upc": "998877665544",
        "mpn": "",
        "product_GTIN": "",
        "parent_product_id": "PARENT-2",
        "merchant_product_category_path": "Fragrance > Men",
        "merchant_product_second_category": "Men",
        "merchant_product_third_category": "Gift Set",
        "product_type": "Perfume",
        "keywords": "gift set edt",
        "specifications": "gift box",
        "in_stock": "1",
        "stock_quantity": "3",
        "stock_status": "in stock",
        "is_for_sale": "1",
        "web_offer": "0",
        "pre_order": "0",
        "valid_from": "2026-05-21",
        "valid_to": "2026-06-21",
        "delivery_cost": "5.00",
        "delivery_time": "72h",
        "large_image": "https://example.test/large-2.jpg",
        "merchant_thumb_url": "https://example.test/thumb-2.jpg",
        "alternate_image": "",
        "alternate_image_two": "",
        "alternate_image_three": "",
        "alternate_image_four": "",
        "commission_group": "default",
    },
    {
        "aw_product_id": "3",
        "merchant_product_id": "SKU-3",
        "product_name": "Coco Mademoiselle Body Lotion 200 ml",
        "aw_deep_link": "https://example.test/deep-link-3",
        "merchant_deep_link": "",
        "merchant_image_url": "https://example.test/image-3.jpg",
        "aw_image_url": "",
        "description": "Body lotion for daily use.",
        "merchant_category": "Fragrance",
        "search_price": "55.00",
        "store_price": "",
        "merchant_name": "Comas",
        "merchant_id": "105475",
        "category_name": "Fragrance",
        "category_id": "12",
        "currency": "EUR",
        "display_price": "55,00 EUR",
        "data_feed_id": "97867",
        "brand_name": "",
        "brand_id": "",
        "ean": "",
        "upc": "",
        "mpn": "",
        "product_GTIN": "",
        "parent_product_id": "PARENT-3",
        "merchant_product_category_path": "Fragrance > Women",
        "merchant_product_second_category": "Women",
        "merchant_product_third_category": "Body",
        "product_type": "Body Care",
        "keywords": "body lotion",
        "specifications": "lotion",
        "in_stock": "",
        "stock_quantity": "",
        "stock_status": "",
        "is_for_sale": "1",
        "web_offer": "0",
        "pre_order": "0",
        "valid_from": "2026-05-21",
        "valid_to": "2026-06-21",
        "delivery_cost": "",
        "delivery_time": "",
        "large_image": "https://example.test/large-3.jpg",
        "merchant_thumb_url": "",
        "alternate_image": "",
        "alternate_image_two": "",
        "alternate_image_three": "",
        "alternate_image_four": "",
        "commission_group": "default",
    },
    {
        "aw_product_id": "4",
        "merchant_product_id": "SKU-4",
        "product_name": "Diptyque Candle 190 g",
        "aw_deep_link": "https://example.test/deep-link-4",
        "merchant_deep_link": "",
        "merchant_image_url": "https://example.test/image-4.jpg",
        "aw_image_url": "",
        "description": "Home candle.",
        "merchant_category": "Home",
        "search_price": "45.00",
        "store_price": "",
        "merchant_name": "Comas",
        "merchant_id": "105475",
        "category_name": "Home",
        "category_id": "99",
        "currency": "EUR",
        "display_price": "45,00 EUR",
        "data_feed_id": "97867",
        "brand_name": "Diptyque",
        "brand_id": "DIP",
        "ean": "",
        "upc": "",
        "mpn": "CANDLE-190",
        "product_GTIN": "",
        "parent_product_id": "PARENT-4",
        "merchant_product_category_path": "Home > Candle",
        "merchant_product_second_category": "Home",
        "merchant_product_third_category": "Candle",
        "product_type": "Home",
        "keywords": "candle",
        "specifications": "wax candle",
        "in_stock": "1",
        "stock_quantity": "8",
        "stock_status": "in stock",
        "is_for_sale": "1",
        "web_offer": "0",
        "pre_order": "0",
        "valid_from": "2026-05-21",
        "valid_to": "2026-06-21",
        "delivery_cost": "7.00",
        "delivery_time": "48h",
        "large_image": "https://example.test/large-4.jpg",
        "merchant_thumb_url": "https://example.test/thumb-4.jpg",
        "alternate_image": "",
        "alternate_image_two": "",
        "alternate_image_three": "",
        "alternate_image_four": "",
        "commission_group": "default",
    },
]


class FakeFetcher:
    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def build_settings(tmp_path: Path, api_key: str = "feed-key") -> Settings:
    return Settings.model_validate(
        {
            "AFFILIATE_DATA_DIR": str(tmp_path),
            "AWIN_PRODUCT_FEED_API_KEY": api_key,
            "DATABASE_URL": "postgresql://ignored:ignored@db:5432/mes_fragrances",
        }
    )


def build_csv_text() -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADER)
    writer.writeheader()
    writer.writerows(ROWS)
    return buffer.getvalue()


def build_csv_bytes() -> bytes:
    return build_csv_text().encode("utf-8")


def build_gzip_bytes() -> bytes:
    return gzip.compress(build_csv_bytes())


def build_flaconi_csv_bytes() -> bytes:
    header = [
        "data_feed_id",
        "merchant_id",
        "merchant_name",
        "aw_product_id",
        "aw_deep_link",
        "aw_image_url",
        "aw_thumb_url",
        "category_id",
        "category_name",
        "brand_id",
        "brand_name",
        "merchant_product_id",
        "merchant_category",
        "ean",
        "product_name",
        "description",
        "merchant_deep_link",
        "merchant_image_url",
        "delivery_time",
        "currency",
        "search_price",
        "store_price",
        "rrp_price",
        "delivery_cost",
        "in_stock",
        "product_type",
        "colour",
        "base_price",
        "base_price_amount",
        "base_price_text",
    ]
    rows = [
        {
            "data_feed_id": "97463",
            "merchant_id": "87361",
            "merchant_name": "Flaconi FR",
            "aw_product_id": "1001",
            "aw_deep_link": "https://awin.test/flaconi-edp",
            "aw_image_url": "https://images.test/flaconi-edp.jpg",
            "aw_thumb_url": "https://images.test/flaconi-edp-thumb.jpg",
            "category_id": "",
            "category_name": "",
            "brand_id": "DG",
            "brand_name": "Dolce & Gabbana",
            "merchant_product_id": "flaconi-1001",
            "merchant_category": "Eau de parfum",
            "ean": "1234567890123",
            "product_name": "Dolce & Gabbana Devotion Eau de parfum 50 ml",
            "description": "Parfum floral 50 ml",
            "merchant_deep_link": "https://merchant.test/flaconi-edp",
            "merchant_image_url": "https://merchant.test/flaconi-edp.jpg",
            "delivery_time": "4-5 jours",
            "currency": "EUR",
            "search_price": "84.99",
            "store_price": "false",
            "rrp_price": "99.99",
            "delivery_cost": "0.00",
            "in_stock": "1",
            "product_type": "Eau de parfum",
            "colour": "",
            "base_price": "1699.80",
            "base_price_amount": "1000",
            "base_price_text": "ml",
        },
        {
            "data_feed_id": "97463",
            "merchant_id": "87361",
            "merchant_name": "Flaconi FR",
            "aw_product_id": "1002",
            "aw_deep_link": "https://awin.test/flaconi-home",
            "aw_image_url": "https://images.test/flaconi-home.jpg",
            "aw_thumb_url": "https://images.test/flaconi-home-thumb.jpg",
            "category_id": "",
            "category_name": "",
            "brand_id": "MF",
            "brand_name": "Millefiori Milano",
            "merchant_product_id": "flaconi-1002",
            "merchant_category": "Parfum d'ambiance",
            "ean": "2234567890123",
            "product_name": "Millefiori Milano Natural Sandalo Bergamotto Parfum d'ambiance",
            "description": "Diffuseur pour la maison",
            "merchant_deep_link": "https://merchant.test/flaconi-home",
            "merchant_image_url": "https://merchant.test/flaconi-home.jpg",
            "delivery_time": "4-5 jours",
            "currency": "EUR",
            "search_price": "29.99",
            "store_price": "false",
            "rrp_price": "29.99",
            "delivery_cost": "3.95",
            "in_stock": "1",
            "product_type": "Parfum d'ambiance",
            "colour": "",
            "base_price": "299.90",
            "base_price_amount": "1000",
            "base_price_text": "ml",
        },
        {
            "data_feed_id": "97463",
            "merchant_id": "87361",
            "merchant_name": "Flaconi FR",
            "aw_product_id": "1003",
            "aw_deep_link": "https://awin.test/flaconi-hair",
            "aw_image_url": "https://images.test/flaconi-hair.jpg",
            "aw_thumb_url": "https://images.test/flaconi-hair-thumb.jpg",
            "category_id": "",
            "category_name": "",
            "brand_id": "BYR",
            "brand_name": "Byredo",
            "merchant_product_id": "flaconi-1003",
            "merchant_category": "Parfum cheveux",
            "ean": "3234567890123",
            "product_name": "Byredo Blanche Hair Mist 75 ml",
            "description": "Hair perfume 75 ml",
            "merchant_deep_link": "https://merchant.test/flaconi-hair",
            "merchant_image_url": "https://merchant.test/flaconi-hair.jpg",
            "delivery_time": "4-5 jours",
            "currency": "EUR",
            "search_price": "64.00",
            "store_price": "false",
            "rrp_price": "64.00",
            "delivery_cost": "0.00",
            "in_stock": "1",
            "product_type": "Parfum cheveux",
            "colour": "",
            "base_price": "853.33",
            "base_price_amount": "1000",
            "base_price_text": "ml",
        },
        {
            "data_feed_id": "97463",
            "merchant_id": "87361",
            "merchant_name": "Flaconi FR",
            "aw_product_id": "1004",
            "aw_deep_link": "https://awin.test/flaconi-makeup",
            "aw_image_url": "https://images.test/flaconi-makeup.jpg",
            "aw_thumb_url": "https://images.test/flaconi-makeup-thumb.jpg",
            "category_id": "",
            "category_name": "",
            "brand_id": "SMB",
            "brand_name": "Smashbox",
            "merchant_product_id": "flaconi-1004",
            "merchant_category": "Rouge à lèvres",
            "ean": "4234567890123",
            "product_name": "Smashbox Always On Rouge à lèvres",
            "description": "Couleur intense",
            "merchant_deep_link": "https://merchant.test/flaconi-makeup",
            "merchant_image_url": "https://merchant.test/flaconi-makeup.jpg",
            "delivery_time": "4-5 jours",
            "currency": "EUR",
            "search_price": "19.99",
            "store_price": "false",
            "rrp_price": "24.99",
            "delivery_cost": "3.95",
            "in_stock": "1",
            "product_type": "Rouge à lèvres",
            "colour": "Rouge",
            "base_price": "1999.00",
            "base_price_amount": "1000",
            "base_price_text": "g",
        },
    ]
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)
    return gzip.compress(buffer.getvalue().encode("utf-8"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Eau de Parfum  ", "eau de parfum"),
        ("Déodorant Coffret", "deodorant coffret"),
    ],
)
def test_normalize_text(value: str, expected: str) -> None:
    assert normalize_text(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("129,99 EUR", 129.99),
        ("1,299.95", 1299.95),
        ("1.299,95", 1299.95),
        ("", None),
    ],
)
def test_parse_price(value: str, expected: float | None) -> None:
    assert parse_price(value) == expected


@pytest.mark.parametrize(
    ("product_name", "description", "expected"),
    [
        ("Eau de Parfum 50 ml", None, 50.0),
        ("Coffret 2 x 50 ml", None, 100.0),
        ("Bottle", "Contains 1.5 l refill", 1500.0),
        ("No size", None, None),
    ],
)
def test_parse_volume_ml(
    product_name: str,
    description: str | None,
    expected: float | None,
) -> None:
    assert parse_volume_ml(product_name, description) == expected


@pytest.mark.parametrize(
    ("product_name", "description", "expected"),
    [
        ("Sauvage Eau de Toilette", None, "EDT"),
        ("La Vie Est Belle", "Eau de Parfum spray", "EDP"),
        ("Fresh scent", "Eau Fraiche body mist", "EAU_FRAICHE"),
        ("Unknown", None, None),
    ],
)
def test_parse_concentration(
    product_name: str,
    description: str | None,
    expected: str | None,
) -> None:
    assert parse_concentration(product_name, description) == expected


def test_detect_exclusion_reasons() -> None:
    reasons = detect_exclusion_reasons(
        "Coffret Testeur Recharge Bougie",
        "Body lotion and shower gel included.",
    )

    assert reasons == {"set_or_bundle", "tester", "refill", "body_product"}


@pytest.mark.parametrize(
    ("product_name", "description"),
    [
        (
            "Cacharel Rose Mallow All Over Perfume Mist Spray pour le corps 100 ml",
            None,
        ),
        ("Generic Body Mist 150 ml", None),
        ("Maison Perfume Mist 100 ml", None),
        ("Brume parfumee corps 100 ml", None),
        ("Hair Mist 75 ml", None),
        ("Body Lotion 200 ml", None),
        ("Shower Gel 200 ml", None),
        ("Deodorant Spray 150 ml", None),
        ("Refill 100 ml", None),
        ("Gift Set Eau de parfum 50 ml", None),
    ],
)
def test_detect_exclusion_reasons_blocks_non_comparable_body_products(
    product_name: str,
    description: str | None,
) -> None:
    reasons = detect_exclusion_reasons(product_name, description)

    assert "body_product" in reasons or "refill" in reasons or "set_or_bundle" in reasons


@pytest.mark.parametrize(
    ("product_name", "description"),
    [
        ("Sauvage Eau de Parfum Spray 100 ml", None),
        ("Terre d'Hermes Eau de Toilette Spray 50 ml", None),
        ("Classic Parfum Spray 30 ml", None),
    ],
)
def test_detect_exclusion_reasons_keeps_regular_perfume_spray(
    product_name: str,
    description: str | None,
) -> None:
    assert "body_product" not in detect_exclusion_reasons(product_name, description)


def test_count_categories() -> None:
    counts = count_categories(ROWS)

    assert counts == {"Fragrance": 3, "Home": 1}


def test_calculate_coverage_percent() -> None:
    assert calculate_coverage_percent(2, 3) == 66.7
    assert calculate_coverage_percent(0, 0) == 0.0


def test_preprocess_feed_with_local_plain_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "comas.csv"
    csv_path.write_bytes(build_csv_bytes())

    report, report_path = FeedPreprocessor(build_settings(tmp_path)).preprocess_feed(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
    )

    assert report["status"] == "success"
    assert report["source"] == "local_file"
    assert report["rows_total"] == 4
    assert report["rows_fragrance"] == 3
    assert report["rows_with_brand_name"] == 3
    assert report["rows_with_any_identifier"] == 3
    assert report["rows_with_ean"] == 1
    assert report["rows_with_upc"] == 1
    assert report["rows_with_mpn"] == 1
    assert report["rows_with_gtin"] == 1
    assert report["rows_with_valid_price"] == 4
    assert report["rows_with_affiliate_url"] == 4
    assert report["rows_with_volume_ml"] == 3
    assert report["rows_with_concentration"] == 2
    assert report["rows_excluded_set_or_bundle"] == 1
    assert report["rows_excluded_body_product"] == 2
    assert report["estimated_matchable_rows"] == 1
    assert report["category_counts"] == {"Fragrance": 3, "Home": 1}
    assert report["brand_name_coverage_percent"] == 66.7
    assert report["identifier_coverage_percent"] == 66.7
    assert report["volume_coverage_percent"] == 100.0
    assert report["affiliate_url_coverage_percent"] == 100.0
    assert report["price_coverage_percent"] == 100.0
    assert report["decision"]["brand_name_coverage"] == "medium"
    assert report["decision"]["recommendation"] == "proceed_to_db_staging"
    assert report["database_write_performed"] is False
    assert report_path.exists()


def test_preprocess_feed_with_local_gzip_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "comas.csv.gz"
    csv_path.write_bytes(build_gzip_bytes())

    report, _ = FeedPreprocessor(build_settings(tmp_path)).preprocess_feed(
        advertiser_id="105475",
        feed_id="97867",
        path=csv_path,
    )

    assert report["compression"] == "gzip"
    assert report["rows_total"] == 4


def test_preprocess_feed_supports_flaconi_profile(tmp_path: Path) -> None:
    csv_path = tmp_path / "flaconi.csv.gz"
    csv_path.write_bytes(build_flaconi_csv_bytes())

    report, _ = FeedPreprocessor(build_settings(tmp_path)).preprocess_feed(
        advertiser_id="87361",
        feed_id="97463",
        path=csv_path,
    )

    assert report["status"] == "success"
    assert report["missing_required_columns"] == []
    assert report["rows_total"] == 4
    assert report["rows_fragrance"] == 1
    assert report["rows_with_valid_price"] == 4
    assert report["rows_with_any_identifier"] == 4
    assert report["rows_with_affiliate_url"] == 4
    assert report["estimated_matchable_rows"] == 1
    assert report["category_counts"]["Eau de parfum"] == 1


def test_preprocess_feed_with_configured_url(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, api_key="")
    fetcher = FakeFetcher({CONFIGURED_DOWNLOAD_URL: build_gzip_bytes()})

    report, report_path = FeedPreprocessor(
        settings,
        fetcher=fetcher,
        environ={"AWIN_FEED_URL_105475_97867": CONFIGURED_DOWNLOAD_URL},
    ).preprocess_feed(advertiser_id="105475", feed_id="97867")

    assert fetcher.calls == [CONFIGURED_DOWNLOAD_URL]
    assert report["source"] == "configured_env"
    assert report["download_url_source"] == "configured_env"
    assert report["configured_feed_url_env_var"] == "AWIN_FEED_URL_105475_97867"
    assert report["source_file_or_url_redacted"] is True
    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert "secret-feed-key" not in json.dumps(saved)


def test_preprocess_feed_falls_back_to_feed_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = build_settings(tmp_path)
    feed_list_url = build_feed_list_url("feed-key")
    fetcher = FakeFetcher(
        {
            feed_list_url: FEED_LIST_CSV.encode("utf-8"),
            CONFIGURED_DOWNLOAD_URL: build_gzip_bytes(),
        }
    )

    report, _ = FeedPreprocessor(settings, fetcher=fetcher, environ={}).preprocess_feed(
        advertiser_id="105475",
        feed_id="97867",
    )

    assert fetcher.calls == [feed_list_url, CONFIGURED_DOWNLOAD_URL]
    assert report["source"] == "feed_list"
    assert report["download_url_source"] == "feed_list"
    assert report["remote_last_imported"] == "2026-05-21 12:00:00"


def test_preprocess_feed_missing_credentials_without_configured_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = build_settings(tmp_path, api_key="")

    with pytest.raises(AwinCommandError) as exc_info:
        FeedPreprocessor(settings, environ={}).preprocess_feed(
            advertiser_id="105475",
            feed_id="97867",
        )

    assert "AWIN_PRODUCT_FEED_API_KEY" in str(exc_info.value)


def test_preprocess_feed_report_redacts_url_and_contains_rows_total(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, api_key="")
    fetcher = FakeFetcher({CONFIGURED_DOWNLOAD_URL: build_gzip_bytes()})

    report, report_path = FeedPreprocessor(
        settings,
        fetcher=fetcher,
        environ={"AWIN_FEED_URL_105475_97867": CONFIGURED_DOWNLOAD_URL},
    ).preprocess_feed(advertiser_id="105475", feed_id="97867")

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["rows_total"] == 4
    assert payload["rows_total"] == 4
    assert "<redacted>" in payload["source_reference"]
    assert "secret-feed-key" not in json.dumps(payload)
    assert payload["download_url_redacted"] is True
    assert payload["database_write_performed"] is False
