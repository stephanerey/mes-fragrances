# PLANS.md — Affiliate System

## Purpose

Use this file for long, ambiguous, or multi-step affiliate system work that needs a reviewable execution plan before code changes land.

## When to use

Use a plan for:

- database migrations;
- Docker runtime changes;
- feed importer implementation;
- matching engine changes;
- offer display integration;
- click tracking;
- Awin API integration;
- any change spanning several modules or services.

## Implementation principle

Validate the real Awin feed before implementing heavy database/matching logic.

The first implementation phases must prove that the worker can:

- authenticate/configure Awin access without exposing secrets;
- discover the Comas feed;
- download the gzip CSV automatically;
- validate the selected columns;
- produce a preprocessing report with real feed statistics.

Only after this validation should Codex implement database staging, matching, offers, candidates and front-end integration.

## Implementation roadmap

### PR 1 — Worker Docker skeleton

Goal:

- add `affiliate-worker/` Python project;
- add Dockerfile;
- add config loading;
- add CLI skeleton;
- add `.env.example`;
- document execution commands.

Acceptance:

- container builds;
- `python -m app.main --help` works;
- no public ports are exposed;
- no secrets committed.

### PR 2 — Awin feed discovery/download smoke test

Goal:

- validate Awin feed credentials/configuration;
- download or parse the Awin Product Feed List;
- locate advertiser `105475` / feed `97867`;
- read remote `Last Imported` and feed download metadata;
- download the gzip CSV in dry-run/download-only mode;
- parse the CSV header without importing to DB;
- write a safe report.

Acceptance:

- Awin feed is discovered;
- gzip CSV can be downloaded and opened;
- header is parsed;
- required and robust-matching columns are reported present/missing;
- no DB mutation is required;
- no secrets or full signed URLs are logged.

### PR 3 — Awin feed preprocessing report

Goal:

- parse the downloaded/local feed without DB writes;
- count rows by category;
- count usable fragrance rows;
- measure coverage for brand, EAN/GTIN/MPN/UPC, stock, images, delivery and category path fields;
- parse prices, volume and concentration;
- report exclusions such as coffrets/testers/body products.

Acceptance:

- preprocessing report quantifies feed quality;
- report identifies whether feed columns are sufficient for matching;
- no offers/candidates/products are created;
- next database/matching decisions can rely on measured feed quality.

### PR 4 — Database migrations

Goal:

- inspect CIS schema;
- add isolated affiliate tables;
- add product variants if needed after schema confirmation;
- seed Comas advertiser/feed.

Acceptance:

- migrations apply cleanly;
- existing product pages remain unaffected;
- rollback notes exist;
- product table assumptions are documented.

### PR 5 — Raw staging import

Goal:

- import local or downloaded Comas CSV into raw staging;
- create import run;
- persist raw rows;
- write report.

Acceptance:

- import is idempotent;
- row counts are reported;
- invalid file errors are clear;
- raw payload is preserved before business logic.

### PR 6 — Normalization and fragrance filtering in pipeline

Goal:

- normalize text, price, category, volume, concentration;
- filter `Fragrance` rows for actionable processing;
- connect preprocessing logic to staged imports.

Acceptance:

- unit tests cover normalization;
- non-fragrance rows do not create offers;
- exclusions are detected and reported.

### PR 7 — Matching and offer upsert

Goal:

- implement matching priority;
- upsert offers;
- track price changes;
- track missed imports;
- deactivate stale offers only after successful imports.

Acceptance:

- no duplicate offers;
- price changes are detected;
- stale offers can be deactivated;
- uncertain rows do not create offers.

### PR 8 — Product candidates

Goal:

- create candidates for unmatched fragrance rows;
- deduplicate candidates;
- preserve match reasons and manual review statuses.

Acceptance:

- no public products are created automatically;
- rejected candidates are not recreated as pending;
- candidates contain enough information for manual review.

### PR 9 — Cron/systemd and operational reports

Goal:

- add production execution docs;
- add report/log locations;
- add dry-run workflow;
- add concurrency protection.

Acceptance:

- daily execution command documented;
- latest report is easy to inspect;
- failed imports do not deactivate offers;
- logs/reports contain no secrets.

### PR 10 — CIS offer display

Goal:

- display active offers on product pages;
- use sponsored/nofollow links;
- hide empty state cleanly.

Acceptance:

- products with no offers still render;
- offers sort by stock and total price;
- inactive offers are hidden.

### PR 11 — Click tracking

Goal:

- add internal redirect route;
- log clicks;
- generate click reference;
- update offer display to use internal click route.

Acceptance:

- redirect works;
- click events are stored;
- no open redirect vulnerability exists;
- no raw secrets in logs.

### PR 12 — Awin transactions and performance

Goal:

- import transaction/performance reports;
- reconcile click references;
- prepare revenue and advertiser performance reporting.

Acceptance:

- transactions can be linked to offers/campaigns where possible;
- unmatched transactions are preserved;
- advertiser performance data can inform sorting later.

## ExecPlan template

### Title

Short name of the plan.

### Goal

What should be true when the work is complete.

### Context

Relevant repository paths, PRD docs, domain docs, constraints, and known pain points.

### Non-negotiable invariants

List the behaviors, contracts, and constraints that must remain true.

### Assumptions and unknowns

Record what is assumed and what still needs validation.

### Milestones

1. Milestone name
   - expected outcome
   - files or areas likely impacted
   - validation method
2. ...

### Verification

Commands, tests, manual checks, and acceptance signals.

### Decision log

Keep a dated log of important decisions or scope adjustments.

### Progress log

Record what has been completed and what remains.
