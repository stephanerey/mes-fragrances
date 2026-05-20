# Codex Task PR07 — Matching and Offer Upsert

## Goal

Match normalized fragrance feed items to existing catalog products/variants and create or update affiliate offers.

## Branch

```text
feat/matching-offer-upsert
```

## Prerequisites

- PR03 Awin preprocessing report merged and reviewed.
- PR04 database migrations merged.
- PR05 raw staging import merged.
- PR06 normalization/fragrance filtering merged.
- Existing CIS product schema inspected and documented in `00_environment/vps_inventory.md`.

## Scope

Implement:

- product/variant lookup helpers;
- external locked mapping lookup;
- exact identifier matching where available;
- deterministic variant key matching;
- guarded fuzzy matching if safe;
- match scoring and match reason;
- offer upsert for confidently matched rows;
- price change tracking;
- `last_seen_at` updates;
- `missed_imports` reset for seen offers;
- stale offer detection/deactivation after configured successful imports;
- tests for matching and offer upsert.

## Out of scope

Do not implement:

- product candidate creation for unmatched rows; defer to PR08;
- admin review UI;
- public product creation;
- front-end offer display;
- click tracking;
- Awin transaction import.

## Matching priority

Implement in this order:

1. exact identifiers: EAN, GTIN, UPC, MPN when mapped to product variants;
2. locked `external_product_mappings`;
3. deterministic variant key:

```text
brand + normalized product name + concentration + volume_ml
```

4. guarded fuzzy matching;
5. no match.

## Auto-match guardrails

Auto-match is allowed only when:

- row is actionable fragrance;
- row is not excluded by V1 exclusion keywords;
- brand is compatible;
- volume is compatible when known;
- concentration is compatible when known;
- score threshold is met.

Default thresholds:

```text
AFFILIATE_MATCH_AUTO_THRESHOLD=95
AFFILIATE_MATCH_REVIEW_THRESHOLD=85
```

## Offer upsert behavior

For a matched feed item:

- create or update one `offers` row;
- use `(advertiser_id, network_product_id, merchant_product_id)` as the preferred uniqueness key;
- set `active = true`;
- set `last_seen_at = now()`;
- reset `missed_imports = 0`;
- update price, delivery cost, stock, URLs, image URL and raw payload;
- if price changes, set `last_price_change_at = now()`;
- preserve `first_seen_at`.

## Stale offer behavior

After a successful import for a feed:

- increment `missed_imports` for active offers from that advertiser/feed that were not seen;
- if `missed_imports >= AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS`, set `active = false`;
- do not delete offers.

## Match statuses

Use explicit match statuses:

```text
matched_exact_identifier
matched_locked_mapping
matched_deterministic_key
matched_fuzzy
needs_review
unmatched
excluded
```

PR07 should create offers only for confident matched statuses.

`needs_review`, `unmatched`, and `excluded` are handled as candidates in PR08.

## Tests

Add tests for:

- exact identifier match;
- locked mapping priority;
- deterministic variant key match;
- fuzzy match threshold behavior;
- exclusion prevents auto-offer;
- offer insert;
- offer price update;
- `last_price_change_at` update;
- stale offer deactivation;
- duplicate import idempotence.

## Acceptance criteria

- matched rows create or update offers;
- unmatched rows do not create offers in PR07;
- excluded rows do not create offers;
- offer import is idempotent;
- price changes are tracked;
- stale offers are deactivated after configured missed imports;
- existing catalog data is not overwritten;
- no public catalog product is created.

## PR description must include

- matching methods implemented;
- confidence thresholds used;
- stale offer logic;
- test results;
- known limitations;
- next recommended task: PR08 product candidates.
