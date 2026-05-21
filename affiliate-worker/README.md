# Affiliate Worker

Standalone Python worker for the Mes Fragrances affiliate import pipeline.

PR01 only provides the project skeleton:

- CLI entry point;
- environment-based configuration;
- logging setup;
- safe placeholder import commands;
- Docker image for isolated execution.

Not implemented in PR01:

- database connections or migrations;
- Awin API or feed downloads;
- CSV parsing;
- offer import, matching or upsert logic.

## Local setup

```bash
cd affiliate-worker
pip install -e .[dev]
```

## Local commands

```bash
python -m app.main --help
python -m app.main show-config
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
python -m app.main import-feeds --network awin --dry-run
pytest
ruff check .
```

`show-config` only reports whether secrets are configured. It never prints their values.

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
docker run --rm --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker import-feeds --network awin --dry-run
```

The container exposes no ports and uses `/data/feeds`, `/data/reports`, and `/data/logs`.
