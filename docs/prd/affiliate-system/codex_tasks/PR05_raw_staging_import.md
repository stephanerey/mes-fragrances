# Codex Task PR05 — Raw Staging Import

## Goal

Import local or downloaded Awin/Comas CSV feed rows into raw staging tables.

This PR persists raw rows and import runs only. It must not create offers, candidates, or public catalog products.

## Branch

```text
feat/raw-staging-import
```

## Prerequisites

- PR01 worker Docker skeleton merged.
- PR02 Awin feed discovery/download merged.
- PR03 Awin preprocessing report merged.
- PR04 database migrations merged.
- `migrate-db` has been run on the target environment.

## Scope

Implement:

- local CSV raw staging import;
- downloaded Awin feed raw staging import if PR02 saved feed files;
- source file SHA256 calculation;
- import run creation;
- raw feed row persistence;
- raw row hash calculation;
- idempotent duplicate handling;
- import report JSON;
- dry-run mode;
- tests using small fixtures.

## Required commands

Local file:

```bash
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv
```

Dry-run:

```bash
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
```

Downloaded feed if implemented:

```bash
python -m app.main import-feeds --network awin --raw-stage-only --advertiser 105475 --feed-id 97867
```

## Raw staging behavior

Each CSV row must be stored in `raw_feed_items.raw_payload` as JSON before any business logic.

Use:

```text
network = awin
network_product_id = aw_product_id when available
merchant_product_id = merchant_product_id when available
raw_hash = sha256(canonical JSON row)
```

## Import run behavior

Every non-dry-run import must create a `feed_import_runs` row.

On success:

```text
status = success
rows_total = total parsed rows
rows_errors = 0 unless recoverable row errors are implemented
finished_at set
```

On failure:

```text
status = failed
error_message set
finished_at set
previous successful imports remain intact
```

## Dry-run behavior

Dry-run must:

- open and parse the CSV;
- count rows;
- inspect header;
- validate advertiser/feed exist;
- write a report;
- not insert raw rows;
- not create offers/candidates.

## Report

Write JSON report under `/data/reports/`.

Report fields:

```json
{
  "status": "success",
  "advertiser_id": "105475",
  "feed_id": "97867",
  "rows_total": 7018,
  "rows_inserted": 7018,
  "rows_duplicates": 0,
  "rows_errors": 0,
  "dry_run": false,
  "source_file_sha256": "...",
  "header": ["..."],
  "missing_expected_columns": []
}
```

## Fixtures

Use:

```text
docs/prd/affiliate-system/fixtures/comas_sample.csv
```

or copy it into a test fixture folder if preferred.

Do not commit the full Comas feed.

## Out of scope

Do not implement:

- normalization;
- fragrance filtering beyond reporting category counts;
- matching;
- offer upsert;
- product candidate creation;
- Awin transaction import.

## Validation commands

```bash
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path docs/prd/affiliate-system/fixtures/comas_sample.csv --dry-run
pytest
ruff check .
```

If using a local test database:

```bash
python -m app.main migrate-db
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path docs/prd/affiliate-system/fixtures/comas_sample.csv
```

## Acceptance criteria

- local CSV import command works;
- invalid file path returns a clear error;
- dry-run does not mutate staging tables;
- non-dry-run creates an import run;
- rows are stored as raw JSON;
- duplicate import does not duplicate raw rows uncontrollably;
- report includes row counts, header and source hash;
- no normalization/matching/offers are implemented in this PR.

## PR description must include

- command examples;
- report example;
- test results;
- known limitations;
- next recommended task: PR06 normalization and fragrance filtering.
