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

Implemented in PR05:

- raw staging import from local CSV/gzip files;
- raw staging import from configured Awin Create-a-Feed URLs;
- `feed_import_runs` creation for non-dry-run imports;
- `raw_feed_items` persistence with canonical `raw_hash` deduplication;
- source payload SHA256 calculation and import reports under `/data/reports`.

Implemented in PR06:

- normalized feed item persistence in `normalized_feed_items`;
- `normalize-feed` command for dry-run and persisted normalization;
- text normalization, HTML entity decoding, accent removal and punctuation cleanup;
- price, currency, concentration, volume, stock, image and URL parsing;
- fragrance/actionable filtering and exclusion reason detection;
- JSON normalization reports without touching offers or candidates.

Implemented in PR07:

- conservative `match-offers` command over `normalized_feed_items`;
- locked external mapping lookup and optional exact identifier matching when the
  catalog exposes compatible identifier fields;
- deterministic and guarded fuzzy matching against the CIS `perfumes` catalog;
- affiliate `offers` upsert only for confident matches;
- price change tracking, `last_seen_at` refresh and conservative stale offer
  deactivation;
- JSON matching reports without touching `perfume_offers`, candidates, mappings
  or catalog tables.

Implemented in PR08:

- `create-candidates` command for unmatched and needs-review normalized rows;
- candidate deduplication through `product_match_candidates.dedupe_key`;
- preservation of manual final candidate statuses;
- candidate enrichment payloads for later manual review;
- excluded-row handling for commercially useful sets/refills and optional
  rejected/ignored excluded rows.

Implemented in PR09:

- `run-affiliate-pipeline` orchestration command for daily worker execution;
- aggregate per-feed and per-step JSON operational reports;
- `latest_affiliate_pipeline_report.json` copy for quick inspection;
- PostgreSQL advisory locking to prevent concurrent runs;
- operational systemd templates and a VPS runbook.

Implemented in PR10:

- `sync-perfume-insert-candidates` daily staging sync from
  `product_match_candidates` into `public.perfume_insert_candidates`;
- conservative classification into `SAFE_INSERT_CANDIDATE`,
  `NEEDS_MANUAL_REVIEW`, `POSSIBLE_DUPLICATE`, `VARIANT_OF_EXISTING` and
  `NON_PERFUME_PRODUCT`;
- preservation of manual staging decisions such as `approved`, `promoted`,
  `rejected`, `merged_existing` and `needs_more_info`;
- `first_seen_at` initialization plus `last_seen_at` / `seen_count` tracking for
  recurring candidates;
- Markdown / JSON reporting and CSV export for newly seen
  `SAFE_INSERT_CANDIDATE` rows;
- no automatic promotion into `public.perfumes`.

Implemented in PR13:

- `run-affiliate-pipeline` now continues after `create-candidates` with
  `sync-perfume-insert-candidates`;
- the same daily pipeline also runs `refresh-product-match-candidates` in
  `--dry-run` mode only, for reporting and diagnostics;
- aggregate pipeline reports now include staging sync metrics, refresh dry-run
  metrics, `perfume_insert_candidates` counts, SAFE top brands, and generated
  JSON/Markdown/CSV paths;
- optional Awin-specific email reporting, separate from the server-backup/restic
  email flow;
- no automatic acceptance, no automatic `public.offers` apply, and no automatic
  promotion into `public.perfumes`.

Not implemented yet:

- product variants;
- CIS front-end integration.
- admin/manual review UI.

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
python -m app.main normalize-feed --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main normalize-feed --advertiser 105475 --feed-id 97867
python -m app.main match-offers --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main match-offers --advertiser 105475 --feed-id 97867
python -m app.main create-candidates --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main create-candidates --advertiser 105475 --feed-id 97867
python -m app.main sync-perfume-insert-candidates --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main sync-perfume-insert-candidates --advertiser 105475 --feed-id 97867 --report-dir /data/reports
python -m app.main run-affiliate-pipeline --network awin --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main run-affiliate-pipeline --network awin --advertiser 105475 --feed-id 97867 --skip-refresh-dry-run
python -m app.main run-affiliate-pipeline --network awin --advertiser 105475 --feed-id 97867 --email-report
python -m app.main run-affiliate-pipeline --network awin --random-delay-max-seconds 300
python -m app.main inspect-db
python -m app.main migrate-db --plan
python -m app.main migrate-db --dry-run
python -m app.main migrate-db
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv
python -m app.main import-feeds --network awin --raw-stage-only --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main import-feeds --network awin --raw-stage-only --advertiser 105475 --feed-id 97867
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

For PR05, `import-local-csv` and `import-feeds --raw-stage-only` require `DATABASE_URL`.
Dry-run parses the full CSV or gzip CSV, validates the seeded advertiser/feed,
computes the source SHA256, and writes a JSON report without inserting
`feed_import_runs` or `raw_feed_items`.

Non-dry-run import creates one `feed_import_runs` row and stores every CSV row as
JSON in `raw_feed_items.raw_payload`. Duplicate rows are ignored safely through
`ON CONFLICT DO NOTHING`, and the report includes duplicate counts.

For PR06, `normalize-feed` reads staged rows from `raw_feed_items`, selects the
latest successful import run that actually persisted rows, normalizes each row,
detects fragrance/exclusion signals, and writes a JSON report under `/data/reports`.
In non-dry-run mode, it upserts `normalized_feed_items` by `raw_feed_item_id`.
It does not create offers, candidates, mappings, variants, or modify CIS catalog tables.

For PR07, `match-offers` reads normalized rows from `normalized_feed_items`,
limits processing to actionable fragrance rows, and tries matching in this order:
locked external mappings, exact identifiers when the catalog exposes compatible
fields, deterministic brand/name keys, then guarded fuzzy matching.
Only confident matches create or update affiliate `offers`; excluded rows,
ambiguous rows, review rows and unmatched rows do not create offers.
`match-offers --dry-run` never mutates `offers`.

For PR08, `create-candidates` reuses the PR07 matching rules without touching
affiliate `offers`. It creates or updates `product_match_candidates` for
`needs_review` and `unmatched` rows, preserves manually final statuses such as
`accepted_existing_perfume` / `rejected_duplicate` / `ignored`, and can
optionally include excluded rows as `needs_review`, `rejected_not_perfume`, or
`ignored` candidates depending on the exclusion reason.

For PR09 and PR13, `run-affiliate-pipeline` orchestrates these commands in this
order for each active feed in the database:

1. `import-feeds --raw-stage-only`
2. `normalize-feed`
3. `match-offers`
4. `create-candidates`
5. `sync-perfume-insert-candidates`
6. `refresh-product-match-candidates --dry-run`

By default it processes all active feeds for the selected network. Use
`--advertiser` and `--feed-id` to restrict the run to one feed.

Dry-run still executes all six stages in non-mutating mode and writes an
aggregate report, but it does not insert raw rows, normalized rows, offers,
candidates, or staging rows. The matching stage also forces `--no-stale-update`
during dry-run.

The orchestration command acquires a PostgreSQL advisory lock first. If another
run already holds the lock, the worker writes a `skipped_locked` report and
exits without running any partial pipeline.

In non-dry-run mode, the pipeline also disables stale-offer updates
automatically when the current raw staging import is not a fully materialized
snapshot of the feed. This keeps daily runs conservative with the current
deduplicated raw staging model.

Aggregate pipeline reports are written as:

```text
/data/reports/affiliate_pipeline_YYYYMMDD_HHMMSS_<network>.json
/data/reports/latest_affiliate_pipeline_report.json
```

The latest report is a copied JSON file instead of a symlink so it works
cleanly on the Docker bind mount used on the VPS.

The pipeline-level sync step is blocking: if `sync-perfume-insert-candidates`
fails, `run-affiliate-pipeline` fails. The refresh step is intentionally
non-blocking because it is dry-run only; if the refresh diagnostic fails, the
pipeline stays successful but records a warning and a failed refresh step in the
aggregate report.

For PR10, `sync-perfume-insert-candidates` reads open
`product_match_candidates` rows for one advertiser/feed and syncs them into the
staging table `public.perfume_insert_candidates`.

It can be used independently after `create-candidates`, for example in a daily
follow-up step:

```bash
python -m app.main sync-perfume-insert-candidates --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main sync-perfume-insert-candidates --advertiser 105475 --feed-id 97867 --report-dir /data/reports/daily
```

The command:

- reads only `product_match_candidates`;
- writes only `public.perfume_insert_candidates` unless `--dry-run` is used;
- never promotes rows into `public.perfumes`;
- never auto-approves or auto-promotes candidates;
- preserves manual staging decisions and only refreshes candidate fields while
  `review_status = 'pending'`;
- updates `last_seen_at` and increments `seen_count` for recurring candidates.

For PR11, `refresh-product-match-candidates` revisits historical open
`product_match_candidates` rows that may have become matchable after the CIS
catalog changed.

It is meant for the case where a perfume was added manually to
`public.perfumes`, but the original Awin row lives only in an older import run
and is therefore no longer reprocessed by `match-offers` or `create-candidates`.

Example usage:

```bash
python -m app.main refresh-product-match-candidates --advertiser 105475 --feed-id 97867 --brand MONTALE --dry-run
python -m app.main refresh-product-match-candidates --advertiser 105475 --feed-id 97867 --report-dir /data/reports/daily
```

The command:

- reads historical `product_match_candidates` rows instead of the latest import run;
- updates only `public.product_match_candidates` unless `--dry-run` is used;
- never promotes into `public.perfumes`;
- never touches `public.offers`;
- keeps the workflow conservative by moving refreshed matches to `needs_review`;
- supports `--brand`, `--limit`, `--only-status`, `--min-score`, and `--report-dir`.

For PR12, `apply-reviewed-product-match-candidates` consumes reviewed
`product_match_candidates` rows and creates or updates `public.offers` from
their historical payloads.

It is intended for batches where a human has already validated the candidate
and the worker only needs to materialize the affiliate offer row.

Example usage:

```bash
python -m app.main apply-reviewed-product-match-candidates --advertiser 105475 --feed-id 97867 --dry-run
python -m app.main apply-reviewed-product-match-candidates --advertiser 105475 --feed-id 97867 --brand MONTALE --status accepted_existing_perfume --report-dir /data/reports/daily
python -m app.main apply-reviewed-product-match-candidates --advertiser 105475 --feed-id 97867 --brand MONTALE --status needs_review --allow-needs-review --dry-run
```

The command:

- reads only `product_match_candidates`;
- writes only `public.offers` unless `--dry-run` is used;
- never writes to `public.perfumes`;
- defaults to `status=accepted_existing_perfume`;
- refuses `needs_review` unless `--allow-needs-review` is passed explicitly;
- skips candidates with missing external ids or incomplete offer payloads;
- reuses the existing offer upsert logic from `match-offers`.

Recommended daily workflow:

1. Run `run-affiliate-pipeline`.
2. Review the aggregate report, the sync Markdown report, and the SAFE CSV output.
3. Inspect the refresh dry-run report for historical open candidates that became matchable.
4. Approve candidates manually in CIS staging.
5. Apply reviewed candidates manually if needed.
6. Promote approved rows later with the SQL plan from
   `promote_approved_perfume_insert_candidates.sql`.

`run-affiliate-pipeline` never calls
`apply-reviewed-product-match-candidates`. That step stays manual and
controlled.

## Awin email reporting

The affiliate worker can send a dedicated plain-text email for the Awin daily
pipeline. This is separate from the server-backup/restic email flow.

Supported environment variables:

- `AFFILIATE_EMAIL_REPORT_ENABLED`
- `AFFILIATE_EMAIL_REPORT_TO`
- `AFFILIATE_EMAIL_REPORT_FROM`
- `AFFILIATE_EMAIL_REPORT_SUBJECT_PREFIX`
- `AFFILIATE_EMAIL_REPORT_SEND_ON_SUCCESS`
- `AFFILIATE_EMAIL_REPORT_SEND_ON_FAILURE`
- `AFFILIATE_EMAIL_REPORT_COMMAND`

Behavior:

- email reporting is disabled by default;
- `AFFILIATE_EMAIL_REPORT_COMMAND` supports `sendmail` or `mail`;
- `--email-report` forces an email attempt for the current run;
- `--no-email-report` suppresses email even if the environment enables it;
- failure emails can be sent even when a pipeline stage fails;
- email delivery errors are reported as warnings and do not trigger any write to
  `public.perfumes` or automatic apply actions.

Example environment:

```bash
AFFILIATE_EMAIL_REPORT_ENABLED="true"
AFFILIATE_EMAIL_REPORT_TO="ops@example.net"
AFFILIATE_EMAIL_REPORT_FROM="awin-worker@example.net"
AFFILIATE_EMAIL_REPORT_SUBJECT_PREFIX="[Awin]"
AFFILIATE_EMAIL_REPORT_SEND_ON_SUCCESS="true"
AFFILIATE_EMAIL_REPORT_SEND_ON_FAILURE="true"
AFFILIATE_EMAIL_REPORT_COMMAND="sendmail"
```

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
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker normalize-feed --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker normalize-feed --advertiser 105475 --feed-id 97867
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker match-offers --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker match-offers --advertiser 105475 --feed-id 97867
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker create-candidates --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker create-candidates --advertiser 105475 --feed-id 97867
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker sync-perfume-insert-candidates --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker sync-perfume-insert-candidates --advertiser 105475 --feed-id 97867 --report-dir /data/reports/daily
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker refresh-product-match-candidates --advertiser 105475 --feed-id 97867 --brand MONTALE --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker refresh-product-match-candidates --advertiser 105475 --feed-id 97867 --report-dir /data/reports/daily
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker apply-reviewed-product-match-candidates --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker apply-reviewed-product-match-candidates --advertiser 105475 --feed-id 97867 --brand MONTALE --status accepted_existing_perfume --report-dir /data/reports/daily
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker run-affiliate-pipeline --network awin --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker run-affiliate-pipeline --network awin --advertiser 105475 --feed-id 97867
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker run-affiliate-pipeline --network awin --advertiser 105475 --feed-id 97867 --skip-refresh-dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker run-affiliate-pipeline --network awin --advertiser 105475 --feed-id 97867 --email-report
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker import-feeds --network awin --raw-stage-only --advertiser 105475 --feed-id 97867 --dry-run
docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker import-feeds --network awin --raw-stage-only --advertiser 105475 --feed-id 97867
```

The container exposes no ports and uses `/data/feeds`, `/data/reports`, and `/data/logs`.

For daily VPS execution, PR09 recommends a host `systemd` timer that runs
`docker run --rm` on the existing `mes-fragrances_cis_default` network. See:

- [mes-fragrances-affiliate-worker.service](/home/eva/mes-fragrances/affiliate-worker/deploy/systemd/mes-fragrances-affiliate-worker.service)
- [mes-fragrances-affiliate-worker.timer](/home/eva/mes-fragrances/affiliate-worker/deploy/systemd/mes-fragrances-affiliate-worker.timer)
- [affiliate_worker_operations.md](/home/eva/mes-fragrances/docs/prd/affiliate-system/30_operations/affiliate_worker_operations.md)

Before the first non-dry-run `migrate-db` on the VPS, take a backup:

```bash
mkdir -p ~/db_backups
chmod 700 ~/db_backups

docker exec mes-fragrances_cis-db-1 \
  pg_dump -U pilot -d pilot \
  > ~/db_backups/backup_before_affiliate_pr04_$(date +%Y%m%d_%H%M%S).sql
```

Do not commit the backup, `.env`, `DATABASE_URL`, or any signed Awin URL.
