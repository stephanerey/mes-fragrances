# Codex Task PR02 — Database Migrations

## Goal

Add database migration infrastructure and the first affiliate tables.

## Branch

```text
feat/affiliate-db-migrations
```

## Prerequisite

PR01 must be merged.

Before implementing migrations that touch existing CIS product/catalog tables, inspect the live/dev database schema and update:

```text
docs/prd/affiliate-system/00_environment/vps_inventory.md
```

## Scope

Implement:

- DB connection helper;
- schema inspection command;
- migration runner or documented migration mechanism;
- isolated affiliate tables;
- Comas advertiser/feed seed data;
- rollback notes;
- tests where feasible.

## Required CLI commands

```bash
python -m app.main inspect-db
python -m app.main migrate-db
```

`inspect-db` must report at least:

- DB engine/version if possible;
- public tables;
- candidate product tables;
- columns for candidate product tables.

`migrate-db` must apply only safe migrations by default.

## Tables to create in PR02

Create isolated tables first:

- `advertisers`
- `affiliate_feeds`
- `feed_import_runs`
- `raw_feed_items`
- `offers`
- `product_match_candidates`
- `external_product_mappings`

Also create a migration tracking table if not using an established migration tool.

## Product variants

Do not blindly assume the existing product table is named `products`.

`product_variants` may be:

- created only if the product table is confirmed;
- or added as a guarded/template migration;
- or deferred to a follow-up PR if schema inspection is inconclusive.

## Seed data

Seed first advertiser/feed:

```text
network: awin
advertiser: Perfumerias Comas FR
network_advertiser_id: 105475
network_feed_id: 97867
locale: fr_FR
currency: EUR
active: true
```

## Out of scope

Do not implement:

- CSV import;
- normalization;
- matching;
- offer upsert logic;
- product candidate generation;
- front-end display.

## Safety requirements

- Migrations must be idempotent where practical.
- Existing product pages must not break.
- No existing product rows may be deleted.
- No production backup may be committed.
- Document backup command in PR description.

## Validation commands

Expected local/dev commands:

```bash
python -m app.main inspect-db
python -m app.main migrate-db
pytest
ruff check .
```

## Acceptance criteria

- DB commands are available;
- `DATABASE_URL` is required for DB commands;
- isolated affiliate tables are created;
- Comas advertiser/feed seed exists;
- product table assumptions are either confirmed or deferred;
- rollback notes exist;
- no secrets are committed;
- PR remains limited to migrations/schema foundation.

## PR description must include

- schema inspection summary;
- migration list;
- tables created;
- backup/rollback notes;
- validation commands run;
- any divergence from `database_schema.md`.
