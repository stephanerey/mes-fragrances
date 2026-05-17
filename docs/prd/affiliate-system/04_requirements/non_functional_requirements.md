# Non-Functional Requirements — Affiliate System

## NFR-001 — Isolation

The affiliate worker must run separately from the CIS container.

A worker failure must not bring down the website.

## NFR-002 — No public exposure

The worker must not expose HTTP ports publicly.

It must only access:

- the database through the Docker internal network;
- external affiliate APIs and feed download URLs through outbound HTTPS.

## NFR-003 — Idempotency

All import operations must be safe to retry.

Re-running the same feed must not duplicate raw rows, offers, mappings, or candidates.

## NFR-004 — Secret handling

Secrets must come from environment variables or Docker secrets.

Forbidden:

- hard-coded API keys;
- secrets committed to Git;
- secrets printed in logs;
- feed download URLs containing API keys stored in plain text unless explicitly required and protected.

## NFR-005 — Observability

The worker must log structured execution information.

Minimum log events:

- worker start;
- feed discovery start/end;
- feed download start/end;
- import run created;
- normalization summary;
- matching summary;
- offer upsert summary;
- candidate summary;
- worker success/failure.

## NFR-006 — Performance

The worker must process the initial Comas feed, approximately 7000 rows, without excessive memory usage.

Implementation should favor streaming or chunked processing when practical.

## NFR-007 — Database safety

Bulk imports must use transactions carefully.

The system must avoid long locks on website-critical tables.

## NFR-008 — Rollback

Database migrations must be reviewable and reversible where feasible.

At minimum, every migration must document rollback considerations.

## NFR-009 — Configurability

Key runtime settings must be configurable:

- active advertiser list;
- feed ids;
- import mode;
- missed imports before offer deactivation;
- fuzzy matching thresholds;
- dry-run mode;
- log level.

## NFR-010 — Reproducibility

The worker must be executable locally or on the VPS with documented commands.

Expected commands must be kept in root `AGENTS.md`, PRD docs, or both.

## NFR-011 — Incremental implementation

Codex must implement this system in small PRs. Large unreviewable implementation drops are not acceptable.

## NFR-012 — Data quality over automation

The system must favor safe candidate generation over incorrect automatic catalog publication.