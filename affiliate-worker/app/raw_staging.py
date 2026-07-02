from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from psycopg.types.json import Jsonb

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
from app.db import DatabaseService, DbCommandError
from app.reporting import try_write_report, write_report


class RawStagingError(RuntimeError):
    """Raised when raw staging cannot complete safely."""


@dataclass(frozen=True)
class RawStagingSource:
    source: str
    payload: bytes
    source_reference: str
    source_file_or_url_redacted: bool
    compression_hint: str | None
    delimiter_hint: str | None
    remote_last_imported: str | None
    configured_feed_url_env_var: str | None
    download_url_source: str | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def calculate_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_row_json(row: Mapping[str, str]) -> str:
    return json.dumps(
        dict(row),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def calculate_raw_hash(row: Mapping[str, str]) -> str:
    return hashlib.sha256(canonical_row_json(row).encode("utf-8")).hexdigest()


def read_csv_payload(
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
        raise RawStagingError("Feed is empty and has no CSV header")

    header = [field.strip() for field in reader.fieldnames]
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        row: dict[str, str] = {}
        for raw_key, raw_value in raw_row.items():
            if raw_key is None:
                continue
            row[raw_key.strip()] = raw_value if raw_value is not None else ""
        rows.append(row)

    return header, rows, delimiter, compression


class RawStagingService:
    def __init__(
        self,
        settings: Settings,
        fetcher: AwinFetcher | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.awin_service = AwinService(settings, fetcher=fetcher, environ=environ)
        self.db_service = DatabaseService(settings)

    def import_local_csv(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        path: Path,
        dry_run: bool,
    ) -> tuple[dict[str, object], Path]:
        self.db_service.require_database_url()
        if not path.exists():
            raise RawStagingError(f"Feed file not found: {path}")
        if not path.is_file():
            raise RawStagingError(f"Feed path is not a regular file: {path}")

        payload = path.read_bytes()
        source = RawStagingSource(
            source="local_file",
            payload=payload,
            source_reference="<redacted>",
            source_file_or_url_redacted=True,
            compression_hint="gzip" if payload.startswith(GZIP_MAGIC) else "plain",
            delimiter_hint=None,
            remote_last_imported=None,
            configured_feed_url_env_var=None,
            download_url_source=None,
        )
        return self._stage_rows(
            advertiser_id=advertiser_id,
            feed_id=feed_id,
            dry_run=dry_run,
            source=source,
        )

    def import_remote_feed(
        self,
        *,
        network: str,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
    ) -> tuple[dict[str, object], Path]:
        self.db_service.require_database_url()
        if network != "awin":
            raise RawStagingError(f"Unsupported network for raw staging: {network}")
        source = self._resolve_remote_source(advertiser_id=advertiser_id, feed_id=feed_id)
        return self._stage_rows(
            advertiser_id=advertiser_id,
            feed_id=feed_id,
            dry_run=dry_run,
            source=source,
        )

    def _resolve_remote_source(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
    ) -> RawStagingSource:
        configured_env_var, configured_url = get_configured_feed_url(
            advertiser_id=advertiser_id,
            feed_id=feed_id,
            environ=self.awin_service.environ,
        )
        if configured_url:
            payload = self.awin_service.fetcher(configured_url)
            metadata = parse_download_url_metadata(configured_url)
            return RawStagingSource(
                source="configured_env",
                payload=payload,
                source_reference=redact_url(configured_url) or "<redacted>",
                source_file_or_url_redacted=True,
                compression_hint=metadata["compression"],
                delimiter_hint=metadata["delimiter"],
                remote_last_imported=None,
                configured_feed_url_env_var=configured_env_var,
                download_url_source="configured_env",
            )

        entries, _ = self.awin_service.fetch_feed_entries()
        target_feed = find_feed(entries, advertiser_id=advertiser_id, feed_id=feed_id)
        if target_feed is None or not target_feed.download_url:
            raise AwinCommandError(
                f"Feed {feed_id} for advertiser {advertiser_id} was not found in the Awin feed list"
            )

        payload = self.awin_service.fetcher(target_feed.download_url)
        metadata = parse_download_url_metadata(target_feed.download_url)
        return RawStagingSource(
            source="feed_list",
            payload=payload,
            source_reference=redact_url(target_feed.download_url) or "<redacted>",
            source_file_or_url_redacted=True,
            compression_hint=metadata["compression"],
            delimiter_hint=metadata["delimiter"],
            remote_last_imported=target_feed.last_imported,
            configured_feed_url_env_var=configured_env_var,
            download_url_source="feed_list",
        )

    def _stage_rows(
        self,
        *,
        advertiser_id: str,
        feed_id: str,
        dry_run: bool,
        source: RawStagingSource,
    ) -> tuple[dict[str, object], Path]:
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "raw-stage-import",
            "network": "awin",
            "advertiser_id": advertiser_id,
            "feed_id": feed_id,
            "dry_run": dry_run,
            "source": source.source,
            "source_file_or_url_redacted": source.source_file_or_url_redacted,
            "source_reference": source.source_reference,
            "configured_feed_url_env_var": source.configured_feed_url_env_var,
            "download_url_source": source.download_url_source,
            "download_url_redacted": source.download_url_source is not None,
            "remote_last_imported": source.remote_last_imported,
        }

        import_run_id: int | None = None

        try:
            header, rows, delimiter, compression = read_csv_payload(
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
            source_sha256 = calculate_sha256(source.payload)
            column_report = compare_columns(
                header,
                advertiser_id=advertiser_id,
                feed_id=feed_id,
            )
            rows_missing_stable_external_ids = sum(
                1
                for row in rows
                if not (row.get("aw_product_id") or "").strip()
                and not (row.get("merchant_product_id") or "").strip()
            )

            with self.db_service.connect() as conn:
                advertiser_row, affiliate_feed_row = self._resolve_feed_context(
                    conn,
                    advertiser_id=advertiser_id,
                    feed_id=feed_id,
                )

                rows_inserted = 0
                rows_duplicates: int | None = None
                rows_errors = 0

                report.update(
                    {
                        "status": "success",
                        "format": "csv",
                        "compression": source.compression_hint or compression,
                        "delimiter": source.delimiter_hint or delimiter,
                        "header_count": len(header),
                        "header": header,
                        "rows_total": len(rows),
                        "rows_inserted": 0,
                        "rows_duplicates": None,
                        "rows_errors": 0,
                        "rows_missing_stable_external_ids": rows_missing_stable_external_ids,
                        "import_run_id": None,
                        "advertiser_db_id": advertiser_row["id"],
                        "affiliate_feed_db_id": affiliate_feed_row["id"],
                        "source_file_sha256": source_sha256,
                        "missing_required_columns": column_report["required_columns_missing"],
                        "missing_robust_matching_columns": column_report[
                            "robust_matching_columns_missing"
                        ],
                        "missing_recommended_columns": column_report[
                            "recommended_columns_missing"
                        ],
                    }
                )

                if not dry_run:
                    import_run_id = self._create_import_run(
                        conn,
                        affiliate_feed_db_id=int(affiliate_feed_row["id"]),
                        source_file_sha256=source_sha256,
                        metadata={
                            "source": source.source,
                            "source_reference": source.source_reference,
                            "source_file_or_url_redacted": True,
                            "compression": source.compression_hint or compression,
                            "format": "csv",
                            "delimiter": source.delimiter_hint or delimiter,
                            "header_count": len(header),
                            "header": header,
                            "rows_total": len(rows),
                            "missing_required_columns": column_report[
                                "required_columns_missing"
                            ],
                            "missing_robust_matching_columns": column_report[
                                "robust_matching_columns_missing"
                            ],
                            "missing_recommended_columns": column_report[
                                "recommended_columns_missing"
                            ],
                        },
                    )

                    try:
                        with conn.transaction():
                            for row in rows:
                                network_product_id = (
                                    (row.get("aw_product_id") or "").strip() or None
                                )
                                merchant_product_id = (
                                    (row.get("merchant_product_id") or "").strip() or None
                                )
                                raw_hash = calculate_raw_hash(row)
                                cursor = conn.execute(
                                    """
                                    insert into raw_feed_items (
                                        import_run_id,
                                        advertiser_id,
                                        network,
                                        network_product_id,
                                        merchant_product_id,
                                        raw_payload,
                                        raw_hash
                                    )
                                    values (%s, %s, %s, %s, %s, %s, %s)
                                    on conflict do nothing
                                    """,
                                    (
                                        import_run_id,
                                        int(advertiser_row["id"]),
                                        "awin",
                                        network_product_id,
                                        merchant_product_id,
                                        Jsonb(dict(row)),
                                        raw_hash,
                                    ),
                                )
                                rows_inserted += cursor.rowcount

                            rows_duplicates = len(rows) - rows_inserted - rows_errors
                            self._mark_import_run_success(
                                conn,
                                import_run_id=import_run_id,
                                rows_total=len(rows),
                                rows_errors=rows_errors,
                                metadata={
                                    "source": source.source,
                                    "source_reference": source.source_reference,
                                    "source_file_or_url_redacted": True,
                                    "source_file_sha256": source_sha256,
                                    "compression": source.compression_hint or compression,
                                    "format": "csv",
                                    "delimiter": source.delimiter_hint or delimiter,
                                    "header_count": len(header),
                                    "rows_inserted": rows_inserted,
                                    "rows_duplicates": rows_duplicates,
                                    "rows_missing_stable_external_ids": (
                                        rows_missing_stable_external_ids
                                    ),
                                    "missing_required_columns": column_report[
                                        "required_columns_missing"
                                    ],
                                    "missing_robust_matching_columns": column_report[
                                        "robust_matching_columns_missing"
                                    ],
                                    "missing_recommended_columns": column_report[
                                        "recommended_columns_missing"
                                    ],
                                },
                            )
                    except Exception as exc:
                        self._mark_import_run_failed(
                            conn,
                            import_run_id=import_run_id,
                            rows_total=len(rows),
                            error_message=str(exc),
                            metadata={
                                "source": source.source,
                                "source_reference": source.source_reference,
                                "source_file_or_url_redacted": True,
                                "source_file_sha256": source_sha256,
                            },
                        )
                        raise

                    report["rows_inserted"] = rows_inserted
                    report["rows_duplicates"] = rows_duplicates
                    report["import_run_id"] = import_run_id

                report_path = write_report(
                    self.settings.affiliate_data_dir,
                    "raw_stage_import",
                    report,
                )
                return report, report_path
        except Exception as exc:
            report["error"] = str(exc)
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "raw_stage_import_error",
                report,
            )
            if report_path is not None:
                raise RawStagingError(
                    f"{exc}. Report written to {report_path}"
                ) from exc
            raise RawStagingError(str(exc)) from exc

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
                "Run migrate-db from PR04/PR05 first."
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
                "Run migrate-db from PR04/PR05 first."
            )
        if int(affiliate_feed_row["advertiser_id"]) != int(advertiser_row["id"]):
            raise DbCommandError(
                f"Affiliate feed {feed_id} is not linked to advertiser {advertiser_id}."
            )

        return dict(advertiser_row), dict(affiliate_feed_row)

    def _create_import_run(
        self,
        conn: Any,
        *,
        affiliate_feed_db_id: int,
        source_file_sha256: str,
        metadata: dict[str, object],
    ) -> int:
        with conn.transaction():
            row = conn.execute(
                """
                insert into feed_import_runs (
                    feed_id,
                    status,
                    source_file_sha256,
                    metadata
                )
                values (%s, 'running', %s, %s)
                returning id
                """,
                (
                    affiliate_feed_db_id,
                    source_file_sha256,
                    Jsonb(metadata),
                ),
            ).fetchone()
        if row is None:
            raise RawStagingError("Failed to create feed_import_runs row")
        return int(row["id"])

    def _mark_import_run_success(
        self,
        conn: Any,
        *,
        import_run_id: int,
        rows_total: int,
        rows_errors: int,
        metadata: dict[str, object],
    ) -> None:
        conn.execute(
            """
            update feed_import_runs
            set status = 'success',
                rows_total = %s,
                rows_errors = %s,
                finished_at = now(),
                metadata = %s
            where id = %s
            """,
            (rows_total, rows_errors, Jsonb(metadata), import_run_id),
        )

    def _mark_import_run_failed(
        self,
        conn: Any,
        *,
        import_run_id: int,
        rows_total: int,
        error_message: str,
        metadata: dict[str, object],
    ) -> None:
        with conn.transaction():
            conn.execute(
                """
                update feed_import_runs
                set status = 'failed',
                    rows_total = %s,
                    rows_errors = 0,
                    error_message = %s,
                    finished_at = now(),
                    metadata = %s
                where id = %s
                """,
                (rows_total, error_message[:1000], Jsonb(metadata), import_run_id),
            )


def format_raw_staging_report_summary(report: Mapping[str, object], report_path: Path) -> str:
    lines = [
        f"status={report.get('status')}",
        f"network={report.get('network')}",
        f"source={report.get('source')}",
        f"dry_run={report.get('dry_run')}",
        f"rows_total={report.get('rows_total')}",
        f"rows_inserted={report.get('rows_inserted')}",
        f"rows_duplicates={report.get('rows_duplicates')}",
        f"rows_errors={report.get('rows_errors')}",
        f"import_run_id={report.get('import_run_id')}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)
