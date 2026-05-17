# Acceptance Tests — Affiliate System

## AT-001 — Repository documentation exists

Given the repository is cloned,
when a developer opens `README.md`,
then they can find the PRD entry point under `docs/prd/affiliate-system/START_HERE.md`.

## AT-002 — Worker isolation

Given the Docker Compose stack is configured,
when the affiliate worker is added,
then it runs as a separate service from CIS and exposes no public ports.

## AT-003 — Local CSV import success

Given the Comas CSV feed is available in `/data/feeds/`,
when the worker runs:

```bash
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv
```

then it creates an import run, stages raw rows, filters fragrance rows, and writes a report.

## AT-004 — Idempotent import

Given the same feed is imported twice,
when the second import completes,
then it does not duplicate offers or candidates.

## AT-005 — Dry-run safety

Given dry-run mode is enabled,
when the worker processes a feed,
then it reports what would happen without mutating production offer/candidate tables.

## AT-006 — Fragrance filtering

Given the initial Comas feed contains mixed beauty categories,
when V1 filtering is applied,
then only `Fragrance` rows are eligible for offer/candidate creation.

## AT-007 — Offer price update

Given an existing offer has price `P1`,
when a later feed contains the same offer with price `P2`,
then the offer price is updated and `last_price_change_at` is set.

## AT-008 — Missing offer deactivation

Given an offer is active,
when it is missing from three successful imports,
then it is marked inactive but not deleted.

## AT-009 — Candidate instead of automatic publication

Given a feed row appears to be a valid fragrance but cannot be confidently matched,
when the worker processes it,
then a product candidate is created and no public catalog product is published.

## AT-010 — Locked mapping priority

Given a locked external mapping exists,
when the worker processes the corresponding feed row,
then the locked mapping is used before fuzzy matching.

## AT-011 — Failed import safety

Given a feed download or parse fails,
when the worker exits,
then the import run is marked failed and the website remains able to serve previous offers.

## AT-012 — Secret safety

Given logs and reports are generated,
when they are inspected,
then no Awin API token, product feed key, database password, or secret URL is present.

## AT-013 — Offer display empty state

Given a product has no active offers,
when its page is rendered,
then no broken offer block is displayed.

## AT-014 — Offer display active state

Given a product has active offers,
when its page is rendered,
then offers are displayed sorted by stock and price.

## AT-015 — Sponsored links

Given offer links are rendered,
when HTML is inspected,
then links use `rel="sponsored nofollow"` until internal click tracking replaces direct linking.