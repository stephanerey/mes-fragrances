# VPS / CIS Environment Inventory

This file must be filled by Codex before implementing deployment-sensitive work.

## Repository and deployment

| Field | Value |
|---|---|
| GitHub repository | `stephanerey/mes-fragrances` |
| Repository role | canonical implementation repository |
| VPS project path | `<fill>` |
| Current CIS path on VPS | `<fill>` |
| Git remote configured on VPS | `<fill>` |
| Deployment user | `<fill>` |
| Ubuntu version | `<fill>` |

## Docker / Compose

| Field | Value |
|---|---|
| Docker version | `<fill>` |
| Docker Compose version | `<fill>` |
| Compose file path | `<fill>` |
| Compose project name | `<fill>` |
| CIS service name(s) | `<fill>` |
| Database service name | `<fill>` |
| Caddy service name | `<fill>` |
| Internal Docker network name | `<fill>` |
| Existing volumes | `<fill>` |

## Database

| Field | Value |
|---|---|
| DB engine | `<fill>` |
| DB version | `<fill>` |
| DB host from worker container | `<fill>` |
| DB port | `<fill>` |
| DB name | `<fill>` |
| DB user source | `<fill>` |
| DB password source | `<fill>` |
| Production backup command verified | `<fill>` |

## Existing catalog schema

| Field | Value |
|---|---|
| Product table name | `<fill>` |
| Product primary key | `<fill>` |
| Product name column | `<fill>` |
| Product slug column | `<fill>` |
| Product brand representation | `<fill>` |
| Brand table exists | `<fill>` |
| Brand table name | `<fill>` |
| Existing variant table exists | `<fill>` |
| Existing image/media model | `<fill>` |
| Existing admin framework/UI | `<fill>` |

## Secrets and Awin

| Field | Value |
|---|---|
| Worker `.env` path | `<fill>` |
| `.env` owner/group | `<fill>` |
| `.env` permissions | `<fill>` |
| Awin publisher id configured | `<yes/no>` |
| Awin API token configured | `<yes/no>` |
| Awin product feed key configured | `<yes/no>` |

## Runtime checks

Before implementation PRs that touch the server, record:

```bash
pwd
docker --version
docker compose version
docker compose ps
```

Before database migrations, record the schema inspection result location and backup file path.

## Rule

Do not commit real secrets, passwords, API tokens, signed feed URLs, or production dumps into this file.
