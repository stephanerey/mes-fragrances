from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from app.awin import (
    AwinCommandError,
    AwinService,
    build_configured_feed_url_env_var,
    build_feed_list_url,
    find_feed,
    get_configured_feed_url,
    inspect_gzip_csv,
    parse_feed_list_csv,
    redact_url,
)
from app.awin_feed_mapping import compare_columns
from app.config import Settings

SAMPLE_DOWNLOAD_URL = (
    "https://productdata.awin.com/datafeed/download/apikey/super-secret/fid/97867/"
    "format/csv/language/fr/delimiter/%2C/compression/gzip/adultcontent/1/"
    "columns/aw_product_id%2Cmerchant_product_id%2Cproduct_name"
)

SAMPLE_FEED_LIST = "\n".join(
    [
        "Advertiser ID,Advertiser Name,Primary Region,Membership Status,Feed ID,"
        "Feed Name,Language,Vertical,Last Imported,URL",
        "105475,Perfumerias Comas FR,FR,Joined,97867,Perfumerias Comas FR PDF,"
        f"fr_FR,Retail,2026-05-21 12:00:00,{SAMPLE_DOWNLOAD_URL}",
        "999999,Other Advertiser,GB,Joined,12345,Other Feed,en_GB,Retail,"
        "2026-05-20 08:00:00,"
        "https://productdata.awin.com/datafeed/download/apikey/another-secret/"
        "fid/12345/format/csv/delimiter/%2C/compression/gzip",
    ]
) + "\n"


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
        }
    )


def build_gzip_feed() -> bytes:
    csv_text = "\n".join(
        [
            ",".join(
                [
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
                    "brand_name",
                    "ean",
                    "product_GTIN",
                    "merchant_product_category_path",
                    "in_stock",
                    "stock_status",
                    "large_image",
                    "merchant_thumb_url",
                    "commission_group",
                ]
            ),
            ",".join(
                [
                    "1",
                    "SKU-1",
                    "La Vie Est Belle",
                    "https://example.test/deep-link",
                    "https://example.test/image.jpg",
                    "Description",
                    "Fragrance",
                    "10.99",
                    "Comas",
                    "105475",
                    "Perfume",
                    "12",
                    "EUR",
                    "10,99 EUR",
                    "97867",
                    "Lancome",
                    "1234567890123",
                    "1234567890123",
                    "Fragrance > Women",
                    "1",
                    "in stock",
                    "https://example.test/large.jpg",
                    "https://example.test/thumb.jpg",
                    "default",
                ]
            ),
            ",".join(
                [
                    "2",
                    "SKU-2",
                    "Black Orchid",
                    "https://example.test/deep-link-2",
                    "https://example.test/image-2.jpg",
                    "Description 2",
                    "Fragrance",
                    "20.50",
                    "Comas",
                    "105475",
                    "Perfume",
                    "12",
                    "EUR",
                    "20,50 EUR",
                    "97867",
                    "Tom Ford",
                    "2234567890123",
                    "2234567890123",
                    "Fragrance > Unisex",
                    "1",
                    "in stock",
                    "https://example.test/large-2.jpg",
                    "https://example.test/thumb-2.jpg",
                    "premium",
                ]
            ),
        ]
    )
    return gzip.compress(csv_text.encode("utf-8"))


def test_parse_feed_list_csv_returns_entries() -> None:
    entries = parse_feed_list_csv(SAMPLE_FEED_LIST.encode("utf-8"))

    assert len(entries) == 2
    assert entries[0].advertiser_id == "105475"
    assert entries[0].feed_id == "97867"
    assert entries[0].last_imported == "2026-05-21 12:00:00"


def test_find_feed_by_advertiser_and_feed_id() -> None:
    entries = parse_feed_list_csv(SAMPLE_FEED_LIST.encode("utf-8"))

    feed = find_feed(entries, advertiser_id="105475", feed_id="97867")

    assert feed is not None
    assert feed.feed_name == "Perfumerias Comas FR PDF"


def test_redact_url_hides_api_keys_and_tokens() -> None:
    url = (
        "https://productdata.awin.com/datafeed/download/apikey/super-secret/fid/97867"
        "?token=abc123&foo=bar"
    )

    redacted = redact_url(url)

    assert redacted is not None
    assert "super-secret" not in redacted
    assert "abc123" not in redacted
    assert "<redacted>" in redacted
    assert "foo=bar" in redacted


def test_configured_feed_url_lookup_by_advertiser_and_feed_id() -> None:
    env_var, configured_url = get_configured_feed_url(
        advertiser_id="105475",
        feed_id="97867",
        environ={"AWIN_FEED_URL_105475_97867": SAMPLE_DOWNLOAD_URL},
    )

    assert env_var == "AWIN_FEED_URL_105475_97867"
    assert configured_url == SAMPLE_DOWNLOAD_URL


def test_configured_feed_url_supports_multiple_urls() -> None:
    env = {
        "AWIN_FEED_URL_105475_97867": SAMPLE_DOWNLOAD_URL,
        "AWIN_FEED_URL_999999_12345": "https://example.test/feed-2",
    }

    first_var, first_url = get_configured_feed_url("105475", "97867", environ=env)
    second_var, second_url = get_configured_feed_url("999999", "12345", environ=env)

    assert first_var == build_configured_feed_url_env_var("105475", "97867")
    assert first_url == SAMPLE_DOWNLOAD_URL
    assert second_var == build_configured_feed_url_env_var("999999", "12345")
    assert second_url == "https://example.test/feed-2"


def test_inspect_gzip_csv_parses_header_and_sample_rows() -> None:
    inspection = inspect_gzip_csv(build_gzip_feed(), delimiter_hint=",")

    assert inspection.compression == "gzip"
    assert inspection.format == "csv"
    assert inspection.delimiter == ","
    assert inspection.rows_sampled == 2
    assert inspection.header[0] == "aw_product_id"


def test_compare_columns_reports_missing_fields() -> None:
    coverage = compare_columns(
        [
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
    )

    assert coverage["required_columns_missing"] == []
    assert "brand_name" in coverage["robust_matching_columns_missing"]
    assert "brand_name" in coverage["recommended_columns_missing"]


def test_awin_download_feed_writes_report_with_column_coverage(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    feed_list_url = build_feed_list_url("feed-key")
    fetcher = FakeFetcher(
        {
            feed_list_url: SAMPLE_FEED_LIST.encode("utf-8"),
            SAMPLE_DOWNLOAD_URL: build_gzip_feed(),
        }
    )

    report, report_path = AwinService(settings, fetcher=fetcher).download_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert report["status"] == "success"
    assert report["feed_found"] is True
    assert report["downloaded"] is True
    assert report["compression"] == "gzip"
    assert report["header_count"] == 24
    assert "mpn" in report["robust_matching_columns_missing"]
    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["download_url_redacted"] is True
    assert "super-secret" not in json.dumps(saved)


def test_awin_download_feed_uses_configured_url_before_feed_list(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, api_key="")
    fetcher = FakeFetcher({SAMPLE_DOWNLOAD_URL: build_gzip_feed()})

    report, _ = AwinService(
        settings,
        fetcher=fetcher,
        environ={"AWIN_FEED_URL_105475_97867": SAMPLE_DOWNLOAD_URL},
    ).download_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert fetcher.calls == [SAMPLE_DOWNLOAD_URL]
    assert report["download_url_source"] == "configured_env"
    assert report["configured_feed_url_env_var"] == "AWIN_FEED_URL_105475_97867"
    assert report["download_url_redacted"] is True
    assert report["feed_found"] is True


def test_awin_download_feed_falls_back_to_feed_list_url(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    feed_list_url = build_feed_list_url("feed-key")
    fetcher = FakeFetcher(
        {
            feed_list_url: SAMPLE_FEED_LIST.encode("utf-8"),
            SAMPLE_DOWNLOAD_URL: build_gzip_feed(),
        }
    )

    report, _ = AwinService(settings, fetcher=fetcher, environ={}).download_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    assert fetcher.calls == [feed_list_url, SAMPLE_DOWNLOAD_URL]
    assert report["download_url_source"] == "feed_list"
    assert report["configured_feed_url_env_var"] == "AWIN_FEED_URL_105475_97867"
    assert report["remote_last_imported"] == "2026-05-21 12:00:00"


def test_configured_feed_url_is_redacted_in_report(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, api_key="")
    fetcher = FakeFetcher({SAMPLE_DOWNLOAD_URL: build_gzip_feed()})

    report, report_path = AwinService(
        settings,
        fetcher=fetcher,
        environ={"AWIN_FEED_URL_105475_97867": SAMPLE_DOWNLOAD_URL},
    ).download_feed(
        advertiser_id="105475",
        feed_id="97867",
        dry_run=True,
    )

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["download_url"] == redact_url(SAMPLE_DOWNLOAD_URL)
    assert saved["download_url"] == redact_url(SAMPLE_DOWNLOAD_URL)
    assert "super-secret" not in json.dumps(saved)


def test_awin_download_feed_failure_writes_error_report(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    feed_list_url = build_feed_list_url("feed-key")
    fetcher = FakeFetcher(
        {
            feed_list_url: SAMPLE_FEED_LIST.encode("utf-8"),
            SAMPLE_DOWNLOAD_URL: AwinCommandError(
                f"Awin request failed for {redact_url(SAMPLE_DOWNLOAD_URL)}"
            ),
        }
    )

    with pytest.raises(AwinCommandError, match="Report written to") as exc_info:
        AwinService(settings, fetcher=fetcher).download_feed(
            advertiser_id="105475",
            feed_id="97867",
            dry_run=True,
        )

    assert "super-secret" not in str(exc_info.value)
    reports = sorted((tmp_path / "reports").glob("awin_download_feed_error_*.json"))
    assert reports
    saved = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert saved["status"] == "error"
    assert saved["downloaded"] is False
