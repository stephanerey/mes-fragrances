# VPS / CIS Environment Inventory

This file must be filled by Codex before implementing deployment-sensitive work.

## Repository and deployment

| Field | Value |
|---|---|
| GitHub repository | `stephanerey/mes-fragrances` |
| Repository role | canonical implementation repository |
| VPS project path | `/home/eva/mes-fragrances` |
| Current CIS path on VPS | `/home/eva/mes-fragrances_CIS` |
| Git remote configured on VPS | `origin git@github.com:stephanerey/mes-fragrances.git` |
| Deployment user | `eva` |
| Ubuntu version | `Ubuntu 25.04` |

## Docker / Compose

| Field | Value |
|---|---|
| Docker version | `29.2.1` |
| Docker Compose version | `v5.0.2` |
| Compose file path | `/home/eva/mes-fragrances_CIS/docker-compose.yml` |
| Compose project name | `mes-fragrances_cis` |
| CIS service name(s) | `backend`, `frontend` |
| Database service name | `db` |
| Caddy service name | `caddy` |
| Internal Docker network name | `mes-fragrances_cis_default` |
| Existing volumes | `mes-fragrances_cis_pilot_db`, `mes-fragrances_cis_caddy_data`, `mes-fragrances_cis_caddy_config` |

## Database

| Field | Value |
|---|---|
| DB engine | `PostgreSQL` |
| DB version | `17.9` |
| DB host from worker container | `db` |
| DB port | `5432` |
| DB name | `pilot` |
| DB user source | `affiliate-worker/.env -> DATABASE_URL` |
| DB password source | `affiliate-worker/.env -> DATABASE_URL` |
| Production backup command verified | `docker exec mes-fragrances_cis-db-1 pg_dump -U pilot -d pilot > ~/db_backups/backup_before_affiliate_pr04_<timestamp>.sql` |

## Existing catalog schema

| Field | Value |
|---|---|
| Product table name | `perfumes` |
| Product primary key | `perfumes.id (uuid)` |
| Product name column | `perfumes.name` |
| Product slug column | `perfumes.slug` |
| Product brand representation | `perfumes.brand (varchar)` |
| Brand table exists | `no confirmed dedicated brand table` |
| Brand table name | `n/a` |
| Existing variant table exists | `no` |
| Existing image/media model | `perfumes.image_url` |
| Existing admin framework/UI | `not yet inspected` |

## Secrets and Awin

| Field | Value |
|---|---|
| Worker `.env` path | `/home/eva/mes-fragrances/affiliate-worker/.env` |
| `.env` owner/group | `eva:eva` |
| `.env` permissions | `600` |
| Awin publisher id configured | `yes` |
| Awin API token configured | `yes` |
| Awin product feed key configured | `yes` |

## Runtime checks

Before implementation PRs that touch the server, record:

```bash
pwd
docker --version
docker compose version
docker compose ps
```

Before database migrations, record the schema inspection result location and backup file path.

Current recorded commands:

```bash
pwd
docker --version
docker compose version
docker compose -f /home/eva/mes-fragrances_CIS/docker-compose.yml ps
```

Schema inspection report location:

```text
/home/eva/mes-fragrances/affiliate-worker-data/reports/inspect_db_20260522T133201Z.json
```

Backup file path before non-dry-run migration:

```text
/home/eva/db_backups/backup_before_affiliate_pr04_20260522_133109.sql
```

## Rule

Do not commit real secrets, passwords, API tokens, signed feed URLs, or production dumps into this file.
