from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row

from app.config import Settings
from app.reporting import try_write_report, write_report

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
TRACKING_TABLE = "affiliate_schema_migrations"
AFFILIATE_TABLES = [
    "advertisers",
    "affiliate_feeds",
    "feed_import_runs",
    "raw_feed_items",
    "offers",
    "product_match_candidates",
    "external_product_mappings",
]


class DbCommandError(RuntimeError):
    """Raised when a DB command cannot complete safely."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str
    checksum: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_database_url(database_url: str | None) -> str | None:
    if not database_url:
        return database_url

    parsed = urlsplit(database_url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    username = parsed.username or ""
    if username and parsed.password is not None:
        netloc = f"{username}:<redacted>@{host}{port}"
    else:
        netloc = parsed.netloc

    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if any(token in key.lower() for token in ("password", "secret", "token", "key")):
            query_items.append((key, "<redacted>"))
        else:
            query_items.append((key, value))

    return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query_items), ""))


def normalize_database_url(database_url: str) -> str:
    return re.sub(r"^postgresql\+psycopg://", "postgresql://", database_url, count=1)


def load_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations: list[Migration] = []

    for path in sorted(migrations_dir.glob("*.sql")):
        match = re.match(r"(?P<version>\d+)_(?P<name>[a-z0-9_]+)\.sql$", path.name)
        if match is None:
            raise DbCommandError(
                f"Invalid migration filename: {path.name}. Expected 0001_name.sql format."
            )

        sql = path.read_text(encoding="utf-8").strip()
        if not sql:
            raise DbCommandError(f"Migration file is empty: {path.name}")

        migrations.append(
            Migration(
                version=match.group("version"),
                name=match.group("name"),
                path=path,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )

    return migrations


def plan_migrations(
    migrations: list[Migration],
    applied_versions: set[str],
) -> list[dict[str, object]]:
    return [
        {
            "version": migration.version,
            "name": migration.name,
            "filename": migration.path.name,
            "checksum": migration.checksum,
            "applied": migration.version in applied_versions,
            "pending": migration.version not in applied_versions,
        }
        for migration in migrations
    ]


def select_candidate_catalog_tables(
    columns_by_table: dict[str, list[dict[str, object]]],
) -> list[str]:
    candidates: list[str] = []
    for table_name, columns in columns_by_table.items():
        column_names = {str(column["column_name"]) for column in columns}
        if {"id", "name"}.issubset(column_names) and (
            "slug" in column_names or "brand" in column_names
        ):
            candidates.append(table_name)
    return sorted(candidates)


def select_candidate_offer_tables(
    columns_by_table: dict[str, list[dict[str, object]]],
) -> list[str]:
    candidates: list[str] = []
    for table_name, columns in columns_by_table.items():
        column_names = {str(column["column_name"]) for column in columns}
        if {"price", "affiliate_url"}.issubset(column_names):
            candidates.append(table_name)
    return sorted(candidates)


class DatabaseService:
    def __init__(
        self,
        settings: Settings,
        migrations_dir: Path = MIGRATIONS_DIR,
    ) -> None:
        self.settings = settings
        self.migrations_dir = migrations_dir

    def require_database_url(self) -> str:
        secret = self.settings.database_url
        if secret is None or not secret.get_secret_value():
            raise DbCommandError("Missing required environment variable: DATABASE_URL")
        return secret.get_secret_value()

    def connect(self, *, autocommit: bool = False) -> psycopg.Connection[Any]:
        database_url = normalize_database_url(self.require_database_url())
        return psycopg.connect(database_url, autocommit=autocommit, row_factory=dict_row)

    def inspect_db(self) -> tuple[dict[str, object], Path]:
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "inspect-db",
            "database_url_redacted": True,
        }

        try:
            with self.connect() as conn:
                metadata_row = conn.execute(
                    """
                    select
                        version() as version,
                        current_database() as current_database,
                        current_user as current_user,
                        current_schema() as current_schema
                    """
                ).fetchone()
                if metadata_row is None:
                    raise DbCommandError("Database inspection query returned no metadata")

                columns_by_table = self._load_columns_by_table(conn)
                public_tables = sorted(columns_by_table)
                candidate_catalog_tables = select_candidate_catalog_tables(columns_by_table)
                candidate_offer_tables = select_candidate_offer_tables(columns_by_table)
                candidate_tables = sorted(set(candidate_catalog_tables + candidate_offer_tables))
                indexes_by_table = self._load_indexes_by_table(conn, candidate_tables)
                tracking_exists = self._tracking_table_exists(conn)
                applied_migrations = (
                    self._load_applied_migrations(conn) if tracking_exists else []
                )

                report.update(
                    {
                        "status": "success",
                        "db_engine": "PostgreSQL",
                        "db_version": metadata_row["version"],
                        "current_database": metadata_row["current_database"],
                        "current_user": metadata_row["current_user"],
                        "current_schema": metadata_row["current_schema"],
                        "public_tables": public_tables,
                        "candidate_catalog_tables": [
                            {
                                "table_name": table_name,
                                "columns": columns_by_table[table_name],
                                "indexes": indexes_by_table.get(table_name, []),
                            }
                            for table_name in candidate_catalog_tables
                        ],
                        "candidate_offer_tables": [
                            {
                                "table_name": table_name,
                                "columns": columns_by_table[table_name],
                                "indexes": indexes_by_table.get(table_name, []),
                            }
                            for table_name in candidate_offer_tables
                        ],
                        "affiliate_tables_exist": {
                            table_name: table_name in public_tables
                            for table_name in [*AFFILIATE_TABLES, TRACKING_TABLE]
                        },
                        "migration_tracking_table_exists": tracking_exists,
                        "applied_migrations": applied_migrations,
                        "existing_schema_migration_tables": [
                            table_name
                            for table_name in public_tables
                            if "migration" in table_name or "version" in table_name
                        ],
                    }
                )
                report_path = write_report(
                    self.settings.affiliate_data_dir,
                    "inspect_db",
                    report,
                )
                return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "inspect_db_error",
                report,
            )
            if report_path is not None:
                raise DbCommandError(f"{message}. Report written to {report_path}") from exc
            raise DbCommandError(message) from exc

    def migrate_db(
        self,
        *,
        dry_run: bool = False,
        plan_only: bool = False,
    ) -> tuple[dict[str, object], Path]:
        report: dict[str, object] = {
            "checked_at": _utc_now(),
            "status": "error",
            "command": "migrate-db",
            "dry_run": dry_run,
            "plan_only": plan_only,
            "database_url_redacted": True,
        }

        try:
            migrations = load_migrations(self.migrations_dir)
            with self.connect() as conn:
                tracking_exists = self._tracking_table_exists(conn)
                applied_rows = self._load_applied_migrations(conn) if tracking_exists else []
                applied_versions = {str(row["version"]) for row in applied_rows}
                self._validate_applied_checksums(migrations, applied_rows)
                plan = plan_migrations(migrations, applied_versions)
                pending = [entry for entry in plan if entry["pending"]]

                applied_now: list[dict[str, object]] = []
                if not dry_run and not plan_only and pending:
                    self._ensure_tracking_table(conn)
                    for migration in migrations:
                        if migration.version in applied_versions:
                            continue
                        with conn.transaction():
                            conn.execute(migration.sql)
                            conn.execute(
                                f"""
                                insert into {TRACKING_TABLE} (
                                    version,
                                    name,
                                    checksum
                                )
                                values (%s, %s, %s)
                                on conflict (version) do nothing
                                """,
                                (migration.version, migration.name, migration.checksum),
                            )
                        applied_now.append(
                            {
                                "version": migration.version,
                                "name": migration.name,
                                "filename": migration.path.name,
                            }
                        )
                    tracking_exists = True
                    applied_versions = {
                        str(row["version"])
                        for row in self._load_applied_migrations(conn)
                    }
                    plan = plan_migrations(migrations, applied_versions)
                    pending = [entry for entry in plan if entry["pending"]]

                refreshed_public_tables = self._load_public_table_names(conn)
                report.update(
                    {
                        "status": "success",
                        "migration_tracking_table_exists": tracking_exists,
                        "migration_tracking_table": TRACKING_TABLE,
                        "migrations_dir": str(self.migrations_dir),
                        "migrations_total": len(migrations),
                        "migrations_plan": plan,
                        "pending_migrations": pending,
                        "pending_count": len(pending),
                        "applied_now": applied_now,
                        "applied_count": len(applied_now),
                        "affiliate_tables_exist": {
                            table_name: table_name in refreshed_public_tables
                            for table_name in [*AFFILIATE_TABLES, TRACKING_TABLE]
                        },
                    }
                )
                report_path = write_report(
                    self.settings.affiliate_data_dir,
                    "migrate_db",
                    report,
                )
                return report, report_path
        except Exception as exc:
            message = str(exc)
            report["error"] = message
            report_path = try_write_report(
                self.settings.affiliate_data_dir,
                "migrate_db_error",
                report,
            )
            if report_path is not None:
                raise DbCommandError(f"{message}. Report written to {report_path}") from exc
            raise DbCommandError(message) from exc

    def _load_public_table_names(self, conn: psycopg.Connection[Any]) -> list[str]:
        rows = conn.execute(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public'
            order by table_name
            """
        ).fetchall()
        return [str(row["table_name"]) for row in rows]

    def _load_columns_by_table(
        self,
        conn: psycopg.Connection[Any],
    ) -> dict[str, list[dict[str, object]]]:
        rows = conn.execute(
            """
            select
                table_name,
                column_name,
                data_type,
                is_nullable
            from information_schema.columns
            where table_schema = 'public'
            order by table_name, ordinal_position
            """
        ).fetchall()

        columns_by_table: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            table_name = str(row["table_name"])
            columns_by_table.setdefault(table_name, []).append(
                {
                    "column_name": row["column_name"],
                    "data_type": row["data_type"],
                    "is_nullable": row["is_nullable"] == "YES",
                }
            )
        return columns_by_table

    def _load_indexes_by_table(
        self,
        conn: psycopg.Connection[Any],
        table_names: list[str],
    ) -> dict[str, list[dict[str, object]]]:
        if not table_names:
            return {}

        rows = conn.execute(
            """
            select
                tablename,
                indexname,
                indexdef
            from pg_indexes
            where schemaname = 'public'
              and tablename = any(%s)
            order by tablename, indexname
            """,
            (table_names,),
        ).fetchall()

        indexes_by_table: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            table_name = str(row["tablename"])
            indexes_by_table.setdefault(table_name, []).append(
                {
                    "index_name": row["indexname"],
                    "index_definition": row["indexdef"],
                }
            )
        return indexes_by_table

    def _tracking_table_exists(self, conn: psycopg.Connection[Any]) -> bool:
        row = conn.execute(
            """
            select exists (
                select 1
                from information_schema.tables
                where table_schema = 'public'
                  and table_name = %s
            ) as exists
            """,
            (TRACKING_TABLE,),
        ).fetchone()
        return bool(row["exists"]) if row else False

    def _ensure_tracking_table(self, conn: psycopg.Connection[Any]) -> None:
        conn.execute(
            f"""
            create table if not exists {TRACKING_TABLE} (
                version text primary key,
                name text not null,
                checksum text not null,
                applied_at timestamptz not null default now()
            )
            """
        )

    def _load_applied_migrations(
        self,
        conn: psycopg.Connection[Any],
    ) -> list[dict[str, object]]:
        if not self._tracking_table_exists(conn):
            return []
        rows = conn.execute(
            f"""
            select version, name, checksum, applied_at
            from {TRACKING_TABLE}
            order by version
            """
        ).fetchall()
        applied: list[dict[str, object]] = []
        for row in rows:
            applied.append(
                {
                    "version": row["version"],
                    "name": row["name"],
                    "checksum": row["checksum"],
                    "applied_at": row["applied_at"].isoformat(),
                }
            )
        return applied

    def _validate_applied_checksums(
        self,
        migrations: list[Migration],
        applied_rows: list[dict[str, object]],
    ) -> None:
        checksum_by_version = {migration.version: migration.checksum for migration in migrations}
        for row in applied_rows:
            version = str(row["version"])
            checksum = str(row["checksum"])
            expected_checksum = checksum_by_version.get(version)
            if expected_checksum is None:
                raise DbCommandError(
                    f"Applied migration {version} exists in DB but no local SQL file matches it."
                )
            if checksum != expected_checksum:
                raise DbCommandError(
                    f"Checksum mismatch for migration {version}: DB and local SQL differ."
                )


def format_inspect_db_summary(report: dict[str, object], report_path: Path) -> str:
    candidate_catalog_names = [
        str(entry["table_name"]) for entry in report.get("candidate_catalog_tables", [])
    ]
    candidate_offer_names = [
        str(entry["table_name"]) for entry in report.get("candidate_offer_tables", [])
    ]
    affiliate_existing = report.get("affiliate_tables_exist", {})
    lines = [
        f"status={report.get('status')}",
        f"db_engine={report.get('db_engine')}",
        f"current_database={report.get('current_database')}",
        f"current_user={report.get('current_user')}",
        f"current_schema={report.get('current_schema')}",
        f"public_tables={len(report.get('public_tables', []))}",
        f"candidate_catalog_tables={candidate_catalog_names}",
        f"candidate_offer_tables={candidate_offer_names}",
        f"migration_tracking_table_exists={report.get('migration_tracking_table_exists')}",
        f"affiliate_tables_exist={affiliate_existing}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)


def format_migrate_db_summary(report: dict[str, object], report_path: Path) -> str:
    pending_versions = [
        str(entry["version"]) for entry in report.get("pending_migrations", [])
    ]
    applied_versions = [
        str(entry["version"]) for entry in report.get("applied_now", [])
    ]
    lines = [
        f"status={report.get('status')}",
        f"plan_only={report.get('plan_only')}",
        f"dry_run={report.get('dry_run')}",
        f"migration_tracking_table_exists={report.get('migration_tracking_table_exists')}",
        f"migrations_total={report.get('migrations_total')}",
        f"pending_migrations={pending_versions}",
        f"applied_now={applied_versions}",
        f"affiliate_tables_exist={report.get('affiliate_tables_exist')}",
        f"report_path={report_path}",
    ]
    return "\n".join(lines)
