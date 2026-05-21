# Affiliate Worker

Standalone Python worker for the Mes Fragrances affiliate import pipeline.

PR01 only provides the project skeleton:

- CLI entry point;
- environment-based configuration;
- logging setup;
- safe placeholder import commands;
- Docker image for isolated execution.

Implemented in PR02:

- Awin product feed list discovery via `AWIN_PRODUCT_FEED_API_KEY`;
- target feed lookup for advertiser `105475` / feed `97867`;
- gzip CSV smoke-test download;
- CSV header parsing and column coverage report;
- safe JSON reports under `/data/reports`;
- URL redaction for any signed or API-keyed feed URLs.

Not implemented yet:

- database connections or migrations;
- row-level CSV import into the database;
- offer import, matching or upsert logic.

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
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
python -m app.main import-feeds --network awin --download-only --dry-run
pytest
ruff check .
```

If you are not inside `.venv`, use `python3 -m app.main ...` on Ubuntu instead of `python -m app.main ...`.

`show-config` only reports whether secrets are configured. It never prints their values.

For PR02, `awin-list-feeds` and `awin-download-feed` are non-mutating smoke-test commands.
They can access Awin, download the gzip feed, inspect the header, and write a report, but they do not write to any database.

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
docker run --rm --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker awin-list-feeds --dry-run
docker run --rm --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker awin-download-feed --advertiser 105475 --feed-id 97867 --dry-run
```

The container exposes no ports and uses `/data/feeds`, `/data/reports`, and `/data/logs`.
