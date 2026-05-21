from __future__ import annotations

import csv
import gzip
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.awin_feed_mapping import compare_columns
from app.config import Settings
from app.reporting import try_write_report, write_report

AwinFetcher = Callable[[str], bytes]
GZIP_MAGIC = b"\x1f\x8b"


class AwinCommandError(RuntimeError):
    """Raised when an Awin CLI command cannot complete its smoke test."""


@dataclass(frozen=True)
class AwinFeedEntry:
    advertiser_id: str
    advertiser_name: str | None
    primary_region: str | None
    membership_status: str | None
    feed_id: str
    feed_name: str | None
    language: str | None
    vertical: str | None
    last_imported: str | None
    download_url: str | None


@dataclass(frozen=True)
class CsvInspection:
    header: list[str]
    delimiter: str
    compression: str
    format: str
    rows_sampled: int


def normalize_feed_list_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def redact_url(url: str | None) -> str | None:
    if not url:
        return url

    parsed = urlsplit(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    redacted_parts: list[str] = []

    index = 0
    while index < len(path_parts):
        part = path_parts[index]
        redacted_parts.append(part)
        if part.lower() == "apikey" and index + 1 < len(path_parts):
            redacted_parts.append("<redacted>")
            index += 2
            continue
        index += 1

    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if any(token in key.lower() for token in ("token", "key", "signature", "auth")):
            query_items.append((key, "<redacted>"))
        else:
            query_items.append((key, value))

    redacted_path = "/" + "/".join(redacted_parts)
    redacted_query = urlencode(query_items)
    return urlunsplit((parsed.scheme, parsed.netloc, redacted_path, redacted_query, ""))


def default_fetch(url: str) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "mes-fragrances-affiliate-worker/0.2"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        raise AwinCommandError(
            f"Awin request failed with HTTP {exc.code} for {redact_url(url)}"
        ) from exc
    except URLError as exc:
        raise AwinCommandError(
            f"Awin request failed for {redact_url(url)}: {exc.reason}"
        ) from exc
    except OSError as exc:
        raise AwinCommandError(
            f"Awin request failed for {redact_url(url)}: {exc}"
        ) from exc


def build_feed_list_url(api_key: str) -> str:
    return f"https://productdata.awin.com/datafeed/list/apikey/{quote(api_key, safe='')}"


def parse_feed_list_csv(payload: bytes) -> list[AwinFeedEntry]:
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    entries: list[AwinFeedEntry] = []

    field_aliases = {
        "advertiserid": "advertiser_id",
        "advertisername": "advertiser_name",
        "primaryregion": "primary_region",
        "membershipstatus": "membership_status",
        "feedid": "feed_id",
        "feedname": "feed_name",
        "language": "language",
        "vertical": "vertical",
        "lastimported": "last_imported",
        "url": "download_url",
        "downloadurl": "download_url",
    }

    for raw_row in reader:
        normalized_row: dict[str, str] = {}
        for raw_key, raw_value in raw_row.items():
            if raw_key is None:
                continue
            alias = field_aliases.get(normalize_feed_list_key(raw_key))
            if alias:
                normalized_row[alias] = (raw_value or "").strip()

        advertiser_id = normalized_row.get("advertiser_id", "")
        feed_id = normalized_row.get("feed_id", "")
        if not advertiser_id or not feed_id:
            continue

        entries.append(
            AwinFeedEntry(
                advertiser_id=advertiser_id,
                advertiser_name=normalized_row.get("advertiser_name") or None,
                primary_region=normalized_row.get("primary_region") or None,
                membership_status=normalized_row.get("membership_status") or None,
                feed_id=feed_id,
                feed_name=normalized_row.get("feed_name") or None,
                language=normalized_row.get("language") or None,
                vertical=normalized_row.get("vertical") or None,
                last_imported=normalized_row.get("last_imported") or None,
                download_url=normalized_row.get("download_url") or None,
            )
        )

    return entries


def find_feed(
    entries: list[AwinFeedEntry],
    advertiser_id: str,
    feed_id: str,
) -> AwinFeedEntry | None:
    for entry in entries:
        if entry.advertiser_id == advertiser_id and entry.feed_id == feed_id:
            return entry
    return None


def parse_download_url_metadata(download_url: str | None) -> dict[str, str | None]:
    if not download_url:
        return {"format": None, "compression": None, "delimiter": None}

    path_parts = [part for part in urlsplit(download_url).path.split("/") if part]
    metadata: dict[str, str | None] = {"format": None, "compression": None, "delimiter": None}

    for index, part in enumerate(path_parts[:-1]):
        next_value = unquote(path_parts[index + 1])
        if part == "format":
            metadata["format"] = next_value
        elif part == "compression":
            metadata["compression"] = next_value
        elif part == "delimiter":
            metadata["delimiter"] = next_value

    return metadata


def inspect_gzip_csv(payload: bytes, delimiter_hint: str | None = None) -> CsvInspection:
    if payload.startswith(GZIP_MAGIC):
        decompressed = gzip.decompress(payload)
        compression = "gzip"
    else:
        decompressed = payload
        compression = "plain"

    text = decompressed.decode("utf-8-sig", errors="replace")
    delimiter = delimiter_hint or ","
    sample = text[:4096]

    if not delimiter_hint:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = [column.strip() for column in next(reader)]
    except StopIteration as exc:
        raise AwinCommandError("Downloaded feed is empty and has no CSV header") from exc

    rows_sampled = sum(1 for _ in islice(reader, 10))
    return CsvInspection(
        header=header,
        delimiter=delimiter,
        compression=compression,
        format="csv",
        rows_sampled=rows_sampled,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AwinService:
    def __init__(self, settings: Settings, fetcher: AwinFetcher | None = None) -> None:
        self.settings = settings
        self.fetcher = fetcher or default_fetch

    def require_product_feed_api_key(self) -> str:
        secret = self.settings.awin_product_feed_api_key
        if secret is None or not secret.get_secret_value():
            raise AwinCommandError(
                "Missing required environment variable: AWIN_PRODUCT_FEED_API_KEY"
            )
        return secret.get_secret_value()

    def fetch_feed_entries(self) -> tuple[list[AwinFeedEntry], str]:
        api_key = self.require_product_feed_api_key()
        list_url = build_feed_list_url(api_key)
        payload = self.fetcher(list_url)
        return parse_feed_list_csv(payload), redact_url(list_url) or "<redacted>"

    def list_feeds(
        self,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
    ) -> tuple[dict[str, object], Path]:
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "network": "awin",
            "command": "awin-list-feeds",
            "dry_run": dry_run,
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
        }

        try:
            entries, list_url = self.fetch_feed_entries()
            report["feed_list_url"] = list_url
            report["accessible_feed_count"] = len(entries)

            target_feed = find_feed(entries, advertiser_id=advertiser_id, feed_id=feed_id)
            report["feed_found"] = target_feed is not None

            if target_feed is None:
                raise AwinCommandError(
                    "Feed "
                    f"{feed_id} for advertiser {advertiser_id} was not found in the Awin "
                    "feed list"
                )

            report.update(
                {
                    "status": "success",
                    "advertiser_name": target_feed.advertiser_name,
                    "feed_name": target_feed.feed_name,
                    "language": target_feed.language,
                    "vertical": target_feed.vertical,
                    "membership_status": target_feed.membership_status,
                    "remote_last_imported": target_feed.last_imported,
                    "download_url": redact_url(target_feed.download_url),
                    "download_url_redacted": bool(target_feed.download_url),
                }
            )
            report_path = write_report(
                self.settings.affiliate_data_dir,
                "awin_list_feeds",
                report,
            )
            return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "awin_list_feeds_error",
                report,
            )
            if report_path is not None:
                raise AwinCommandError(f"{message}. Report written to {report_path}") from exc
            raise AwinCommandError(message) from exc

    def download_feed(
        self,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
    ) -> tuple[dict[str, object], Path]:
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "network": "awin",
            "command": "awin-download-feed",
            "dry_run": dry_run,
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "downloaded": False,
        }

        try:
            entries, list_url = self.fetch_feed_entries()
            report["feed_list_url"] = list_url
            report["accessible_feed_count"] = len(entries)

            target_feed = find_feed(entries, advertiser_id=advertiser_id, feed_id=feed_id)
            report["feed_found"] = target_feed is not None

            if target_feed is None:
                raise AwinCommandError(
                    "Feed "
                    f"{feed_id} for advertiser {advertiser_id} was not found in the Awin "
                    "feed list"
                )
            if not target_feed.download_url:
                raise AwinCommandError(
                    "Feed "
                    f"{feed_id} for advertiser {advertiser_id} has no download URL in the "
                    "Awin feed list"
                )

            report.update(
                {
                    "advertiser_name": target_feed.advertiser_name,
                    "feed_name": target_feed.feed_name,
                    "language": target_feed.language,
                    "vertical": target_feed.vertical,
                    "membership_status": target_feed.membership_status,
                    "remote_last_imported": target_feed.last_imported,
                    "download_url": redact_url(target_feed.download_url),
                    "download_url_redacted": True,
                }
            )

            metadata = parse_download_url_metadata(target_feed.download_url)
            payload = self.fetcher(target_feed.download_url)
            inspection = inspect_gzip_csv(payload, delimiter_hint=metadata["delimiter"])
            coverage = compare_columns(inspection.header)

            report.update(
                {
                    "status": "success",
                    "downloaded": True,
                    "compression": metadata["compression"] or inspection.compression,
                    "format": metadata["format"] or inspection.format,
                    "delimiter": inspection.delimiter,
                    "header_count": len(inspection.header),
                    "header": inspection.header,
                    "rows_sampled": inspection.rows_sampled,
                    **coverage,
                }
            )

            report_path = write_report(
                self.settings.affiliate_data_dir,
                "awin_download_feed",
                report,
            )
            return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "awin_download_feed_error",
                report,
            )
            if report_path is not None:
                raise AwinCommandError(f"{message}. Report written to {report_path}") from exc
            raise AwinCommandError(message) from exc


def format_report_summary(report: dict[str, object], report_path: Path) -> str:
    summary = {
        "status": report.get("status"),
        "command": report.get("command"),
        "advertiser_id": report.get("advertiser_id"),
        "feed_id": report.get("feed_id"),
        "feed_found": report.get("feed_found"),
        "downloaded": report.get("downloaded"),
        "remote_last_imported": report.get("remote_last_imported"),
        "header_count": report.get("header_count"),
        "rows_sampled": report.get("rows_sampled"),
        "report_path": str(report_path),
    }
    return json.dumps(summary, indent=2, sort_keys=True)
