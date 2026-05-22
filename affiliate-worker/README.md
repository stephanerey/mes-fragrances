# Affiliate Worker

Standalone Python worker for the Mes Fragrances affiliate import pipeline.

PR01 only provides the project skeleton:

- CLI entry point;
- environment-based configuration;
- logging setup;
- safe placeholder import commands;
- Docker image for isolated execution.

Implemented in PR02 and PR03:

- Awin product feed list discovery via `AWIN_PRODUCT_FEED_API_KEY`;
- target feed lookup for advertiser `105475` / feed `97867`;
- configurable per-feed Create-a-Feed URL override via `AWIN_FEED_URL_<ADVERTISER_ID>_<FEED_ID>`;
- gzip CSV smoke-test download;
- CSV header parsing and column coverage report;
- full-feed preprocessing for coverage, exclusions, and matchability metrics;
- safe JSON reports under `/data/reports`;
- URL redaction for any signed or API-keyed feed URLs.

Implemented in PR04:

- PostgreSQL connection helper via `DATABASE_URL`;
- `inspect-db` schema inspection and JSON reporting;
- `migrate-db` migration planning, dry-run and apply mode;
- SQL migration tracking through `affiliate_schema_migrations`;
- isolated affiliate tables and Comas advertiser/feed seed data.

Not implemented yet:

- row-level CSV import into the database;
- offer import, matching or upsert logic;
- product variants;
- CIS front-end integration.

## Local setup

On Ubuntu hosts outside a virtual environment, prefer `python3 -m ...`.
After activating `.venv`, use `python -m ...`.
For production-style validation, prefer the Docker commands below.

```bash
cd affiliate-worker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Local commands

```bash
python -m app.main --help
python -m app.main show-config
python -m app.main awin-list-feeds --dry-run
python -m app.main awin-download-feed --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main preprocess-feed --advertiser 105475 --feed-id 97867
python -m app.main preprocess-feed --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv.gz
python -m app.main inspect-db
python -m app.main migrate-db --plan
python -m app.main migrate-db --dry-run
python -m app.main migrate-db
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
python -m app.main import-feeds --network awin --download-only --dry-run
pytest
ruff check .
```

If you are not inside `.venv`, use `python3 -m app.main ...` on Ubuntu instead of `python -m app.main ...`.

`show-config` only reports whether secrets are configured. It never prints their values.

For PR02, `awin-list-feeds` and `awin-download-feed` are non-mutating smoke-test commands.
They can access Awin, download the gzip feed, inspect the header, and write a report, but they do not write to any database.

For PR03, `preprocess-feed` parses the full CSV or gzip CSV from either a local file or the configured Awin feed URL.
It writes a feed-quality report under `/data/reports`, including category counts, coverage metrics, exclusion counts, and a decision recommendation, but it still does not write to any database.

For PR04, `inspect-db` and `migrate-db` require `DATABASE_URL`.
`inspect-db` reports the live schema, candidate catalog tables, and existing migration state.
`migrate-db --plan` and `migrate-db --dry-run` are non-mutating. `migrate-db` applies only pending SQL files and writes a JSON report.

PR04 keeps the new affiliate schema additive-only. It references the existing `perfumes(id)` table only where the live schema is already confirmed, and it defers `product_variants` to a later PR.

For scalable production setup, store each Create-a-Feed download URL in a dedicated environment variable:

```bash
AWIN_FEED_URL_<ADVERTISER_ID>_<FEED_ID>=<full-create-a-feed-url>
```

Example variable name for Comas:

```bash
AWIN_FEED_URL_105475_97867=
```

Do not commit any real value. These URLs contain `/apikey/<secret>/` and must be treated as secrets.

`awin-download-feed --advertiser <id> --feed-id <id>` resolves its download URL like this:

1. `AWIN_FEED_URL_<ADVERTISER_ID>_<FEED_ID>` if present.
2. Otherwise, fallback to the Awin feed-list-discovered download URL.

In Awin Create-a-Feed, select all useful product columns where possible and configure:

- format: `csv`
- delimiter: comma
- compression: `gzip`

For local development, copy `.env.example` to `.env`, then fill in your real values outside Git.

## Docker

Build from the repository root:

```bash
docker build -t mes-fragrances-affiliate-worker ./affiliate-worker
```

Run the CLI:

```bash
docker run --rm mes-fragrances-affiliate-worker --help
docker run --rm --env-file ./affiliate-worker/.env mes-fragrances-affiliate-worker show-config
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker inspect-db
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker migrate-db --plan
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker migrate-db --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker migrate-db
docker run --rm --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker awin-list-feeds --dry-run
docker run --rm --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker awin-download-feed --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker preprocess-feed --advertiser 105475 --feed-id 97867
```

The container exposes no ports and uses `/data/feeds`, `/data/reports`, and `/data/logs`.

Before the first non-dry-run `migrate-db` on the VPS, take a backup:

```bash
mkdir -p ~/db_backups
chmod 700 ~/db_backups

docker exec mes-fragrances_cis-db-1 \
  pg_dump -U pilot -d pilot \
  > ~/db_backups/backup_before_affiliate_pr04_$(date +%Y%m%d_%H%M%S).sql
```

Do not commit the backup, `.env`, `DATABASE_URL`, or any signed Awin URL.
