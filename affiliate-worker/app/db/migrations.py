from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
DEFAULT_AUTO_MIGRATIONS = ("0001_affiliate_core.sql",)


@dataclass(frozen=True)
class MigrationResult:
    version: str
    status: str


def list_migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def get_applied_migrations(connection: Connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'affiliate_schema_migrations'
            )
            """
        )
        exists = cursor.fetchone()[0]
        if not exists:
            return set()

        cursor.execute("SELECT version FROM affiliate_schema_migrations")
        return {row[0] for row in cursor.fetchall()}


def apply_migrations(
    connection: Connection,
    *,
    include_templates: bool = False,
) -> list[MigrationResult]:
    applied = get_applied_migrations(connection)
    results: list[MigrationResult] = []

    for path in list_migration_files():
        version = path.name
        if version in applied:
            results.append(MigrationResult(version=version, status="already_applied"))
            continue

        if not include_templates and version not in DEFAULT_AUTO_MIGRATIONS:
            results.append(MigrationResult(version=version, status="skipped_template"))
            continue

        sql = path.read_text(encoding="utf-8")
        with connection.cursor() as cursor:
            cursor.execute(sql)
            cursor.execute(
                """
                INSERT INTO affiliate_schema_migrations (version)
                VALUES (%s)
                ON CONFLICT (version) DO NOTHING
                """,
                (version,),
            )
        results.append(MigrationResult(version=version, status="applied"))

    connection.commit()
    return results


def inspect_public_schema(connection: Connection) -> dict[str, object]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """
        )
        tables = [row[0] for row in cursor.fetchall()]

        candidate_product_tables = [
            table for table in tables if "product" in table.lower() or "produit" in table.lower()
        ]

        columns_by_table: dict[str, list[dict[str, str]]] = {}
        for table in candidate_product_tables:
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table,),
            )
            columns_by_table[table] = [
                {
                    "name": row[0],
                    "data_type": row[1],
                    "nullable": row[2],
                }
                for row in cursor.fetchall()
            ]

    return {
        "tables": tables,
        "candidate_product_tables": candidate_product_tables,
        "columns_by_table": columns_by_table,
    }
