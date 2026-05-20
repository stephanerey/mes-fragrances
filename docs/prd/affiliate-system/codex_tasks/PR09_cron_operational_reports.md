# Codex Task PR09 — Cron/Systemd and Operational Reports

## Goal

Make the affiliate worker safe and practical to run daily on the OVH Ubuntu VPS.

## Branch

```text
feat/cron-operational-reports
```

## Prerequisites

- PR01 worker skeleton merged.
- PR02 Awin feed discovery/download merged.
- PR03 Awin preprocessing report merged.
- PR04 database migrations merged.
- PR05 raw staging import merged.
- PR06 normalization/fragrance filtering merged.
- PR07 matching/offer upsert merged.
- PR08 product candidates merged.
- `00_environment/vps_inventory.md` filled for deployment-relevant fields.

## Scope

Implement/document:

- production execution command;
- cron or systemd timer example;
- dry-run operational workflow;
- report file naming and retention;
- structured JSON reports;
- log location and rotation guidance;
- random startup delay option;
- lock mechanism to prevent concurrent imports;
- failure exit codes;
- manual runbook.

## Out of scope

Do not implement:

- CIS front-end offer display;
- click tracking;
- Awin transactions;
- admin UI.

## Preferred scheduler

V1 may use host cron or systemd timer.

Document both if useful, but choose one production recommendation after inspecting the VPS.

Expected command pattern:

```bash
cd /opt/mes-fragrances && docker compose run --rm affiliate-worker python -m app.main import-feeds --network awin
```

Dry-run:

```bash
cd /opt/mes-fragrances && docker compose run --rm affiliate-worker python -m app.main import-feeds --network awin --dry-run
```

## Locking

Prevent concurrent imports using one of:

- PostgreSQL advisory lock;
- lock file under `/data/locks/`;
- systemd timer settings if using systemd.

Prefer PostgreSQL advisory lock once DB access is available.

## Report naming

Reports should be written under:

```text
/data/reports/
```

Recommended names:

```text
import_YYYYMMDD_HHMMSS_<network>_<advertiser_id>_<feed_id>.json
latest_import_report.json
```

## Report contents

Include:

```json
{
  "status": "success",
  "network": "awin",
  "advertiser_id": "105475",
  "feed_id": "97867",
  "started_at": "...",
  "finished_at": "...",
  "duration_seconds": 0,
  "downloaded": true,
  "skipped_reason": null,
  "remote_last_imported": "...",
  "source_file_sha256": "...",
  "rows_total": 0,
  "rows_raw_inserted": 0,
  "rows_duplicates": 0,
  "rows_fragrance": 0,
  "rows_excluded": 0,
  "offers_created": 0,
  "offers_updated": 0,
  "offers_deactivated": 0,
  "candidates_created": 0,
  "candidates_updated": 0,
  "rows_errors": 0,
  "missing_required_columns": [],
  "missing_recommended_columns": []
}
```

## Failure behavior

On failure:

- return non-zero exit code;
- mark import run failed if DB run exists;
- write failure report;
- do not deactivate offers because of failed imports;
- leave previous website state intact.

## Retention

Initial recommendation:

- keep downloaded feeds for 30 days;
- keep JSON reports indefinitely until manual cleanup policy exists;
- rotate logs via Docker or host logrotate.

## Validation commands

```bash
python -m app.main import-feeds --network awin --dry-run
python -m app.main show-config
pytest
ruff check .
```

On VPS, also validate:

```bash
docker compose run --rm affiliate-worker python -m app.main import-feeds --network awin --dry-run
```

## Acceptance criteria

- daily command is documented;
- dry-run procedure is documented;
- report path and naming are stable;
- latest report is easy to inspect;
- concurrent imports are prevented or explicitly guarded;
- failed import does not deactivate offers;
- logs/reports do not contain secrets;
- VPS inventory is updated where relevant.

## PR description must include

- chosen scheduler strategy;
- exact commands added/documented;
- report sample;
- locking strategy;
- validation results;
- next recommended task: PR10 CIS offer display.
