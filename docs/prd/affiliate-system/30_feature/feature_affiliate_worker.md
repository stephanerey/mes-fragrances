# Feature — Affiliate Worker

## Goal

Create a standalone Python Docker worker responsible for affiliate feed ingestion and offer updates.

## V1 responsibilities

- run as a batch command;
- load configuration from environment;
- connect to the CIS database;
- import a local Comas CSV feed;
- stage raw rows;
- normalize rows;
- filter fragrance rows;
- produce an import report.

## V2 responsibilities

- discover Awin feeds through API/feed list;
- download changed feeds;
- upsert offers;
- create product candidates;
- deactivate stale offers;
- support dry-run mode.

## Commands

Expected V1 commands:

```bash
python -m app.main --help
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
```

Expected later command:

```bash
python -m app.main import-feeds --network awin
```

## Configuration

Configuration must be centralized in `app/config.py` or equivalent.

Required variables:

- `DATABASE_URL`
- `AFFILIATE_LOG_LEVEL`
- `AFFILIATE_IMPORT_MODE`
- `AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS`
- `AFFILIATE_MATCH_AUTO_THRESHOLD`
- `AFFILIATE_MATCH_REVIEW_THRESHOLD`

Awin variables:

- `AWIN_PUBLISHER_ID`
- `AWIN_API_TOKEN`
- `AWIN_PRODUCT_FEED_API_KEY`

## Logging

Logs should be structured and include:

- run id;
- advertiser id;
- feed id;
- row counts;
- status;
- duration;
- error message when applicable.

## Report

The worker must write a JSON report to `/data/reports/`.

Report fields:

```json
{
  "status": "success",
  "advertiser_id": "105475",
  "feed_id": "97867",
  "rows_total": 7018,
  "rows_filtered": 2691,
  "rows_matched": 0,
  "rows_candidates": 0,
  "rows_errors": 0,
  "missing_columns": [],
  "started_at": "...",
  "finished_at": "..."
}
```

## Acceptance criteria

- worker builds in Docker;
- command line help works;
- local CSV import command runs;
- invalid CSV path produces a clear error;
- dry-run does not mutate production tables;
- import run is marked success or failed correctly;
- secrets are not logged.