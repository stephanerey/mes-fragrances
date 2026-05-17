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

### PR 2 — Database migrations

Goal:

- inspect CIS schema;
- add isolated affiliate tables;
- add product variants if needed;
- seed Comas advertiser/feed.

Acceptance:

- migrations apply cleanly;
- existing product pages remain unaffected;
- rollback notes exist.

### PR 3 — Local CSV staging import

Goal:

- import local Comas CSV;
- create import run;
- persist raw rows;
- write report.

Acceptance:

- import is idempotent;
- row counts are reported;
- invalid file errors are clear.

### PR 4 — Normalization and fragrance filtering

Goal:

- normalize text, price, category, volume, concentration;
- filter `Fragrance` rows for actionable processing.

Acceptance:

- unit tests cover normalization;
- non-fragrance rows do not create offers.

### PR 5 — Matching and offer upsert

Goal:

- implement mapping priority;
- upsert offers;
- track price changes;
- track missed imports.

Acceptance:

- no duplicate offers;
- price changes are detected;
- stale offers can be deactivated.

### PR 6 — Product candidates

Goal:

- create candidates for unmatched fragrance rows;
- deduplicate candidates;
- preserve match reasons.

Acceptance:

- no public products are created automatically;
- rejected candidates are not recreated as pending.

### PR 7 — Cron/systemd and operational reports

Goal:

- add production execution docs;
- add report/log locations;
- add dry-run workflow.

Acceptance:

- daily execution command documented;
- latest report is easy to inspect.

### PR 8 — CIS offer display

Goal:

- display active offers on product pages;
- use sponsored/nofollow links;
- hide empty state cleanly.

Acceptance:

- products with no offers still render;
- offers sort by stock and total price.

### PR 9 — Click tracking

Goal:

- add internal redirect route;
- log clicks;
- generate click reference.

Acceptance:

- redirect works;
- click events are stored;
- no raw secrets in logs.

### PR 10 — Awin transactions and performance

Goal:

- import transaction/performance reports;
- reconcile click references;
- prepare revenue dashboards.

Acceptance:

- transactions can be linked to offers/campaigns where possible;
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
