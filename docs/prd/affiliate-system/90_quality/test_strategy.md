# Test Strategy — Affiliate System

## Test levels

### Unit tests

Target modules:

- text normalization;
- perfume concentration parsing;
- volume parsing;
- price parsing;
- category filtering;
- fuzzy scoring;
- candidate status transitions.

### Integration tests

Target flows:

- import local CSV into staging;
- upsert offers;
- update existing offer price;
- create candidates;
- deactivate stale offers;
- respect locked mappings.

### End-to-end smoke tests

Target flows:

- run worker in Docker;
- connect to test database;
- process a sample feed;
- verify report and database state.

## Fixtures

Create small deterministic CSV fixtures:

```text
tests/fixtures/awin/comas_minimal.csv
tests/fixtures/awin/comas_price_change.csv
tests/fixtures/awin/comas_unmatched_candidate.csv
tests/fixtures/awin/comas_non_fragrance.csv
```

## Sample test cases

- `La Vie Est Belle Eau de Parfum 50 ml` parses as concentration `EDP`, volume `50`.
- `Eau de Toilette 100ML` parses as concentration `EDT`, volume `100`.
- `category_name = Fragrance` passes V1 filter.
- `category_name = Skincare` does not create an offer.
- a locked mapping beats a higher fuzzy candidate.
- a rejected candidate is not recreated as pending.

## Database tests

Use a disposable test database.

Tests must not require production data.

## Performance smoke test

The initial Comas-sized feed, approximately 7000 rows, should process within acceptable time and memory limits on the VPS.

The exact performance threshold can be set after observing the first implementation.

## Manual validation checklist

Before production run:

- backup database;
- confirm `.env` values;
- run dry-run;
- inspect report;
- import first feed;
- inspect row counts;
- verify no public product was created automatically;
- verify active offers are reasonable;
- verify website still loads.