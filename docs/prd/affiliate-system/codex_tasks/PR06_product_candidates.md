# Codex Task PR06 — Product Candidates

## Goal

Create and maintain reviewable product candidates for feed rows that are valid or potentially valid fragrances but cannot be confidently matched to existing catalog products/variants.

## Branch

```text
feat/product-candidates
```

## Prerequisites

- PR01 worker skeleton merged.
- PR02 database migrations merged.
- PR03 local CSV staging import merged.
- PR04 normalization/fragrance filtering merged.
- PR05 matching/offer upsert merged.

## Scope

Implement:

- candidate creation for unmatched fragrance rows;
- candidate update/deduplication across imports;
- candidate status preservation;
- proposed product/variant suggestions when fuzzy score is in review range;
- match reason storage;
- source and advertiser counts;
- enrichment payload for parsed fields;
- report counters for candidates created/updated/rejected;
- tests.

## Out of scope

Do not implement:

- admin UI;
- automatic public product creation;
- automatic editorial enrichment;
- front-end display;
- click tracking;
- Awin transactions.

## Candidate creation rules

Create/update a candidate when:

- row is actionable fragrance;
- no confident offer match exists;
- row is not a clear non-fragrance;
- row has a usable title;
- row has an affiliate or merchant URL;
- row is not already rejected/ignored by previous manual review.

## Candidate status rules

Supported statuses:

```text
pending
needs_review
accepted_existing_variant
accepted_new_variant
accepted_new_product
rejected_not_perfume
rejected_duplicate
ignored
```

If a candidate was manually set to rejected/ignored, do not recreate it as pending on every import.

## Candidate deduplication key

Deduplicate using a stable combination such as:

```text
advertiser_id
network_product_id
merchant_product_id
normalized_candidate_name
candidate_concentration
candidate_volume_ml
candidate_brand
```

If external ids are missing, fall back to normalized fields and raw hash with caution.

## Suggested candidates

When fuzzy score is within review range:

```text
AFFILIATE_MATCH_REVIEW_THRESHOLD <= score < AFFILIATE_MATCH_AUTO_THRESHOLD
```

create a candidate with:

- proposed product id;
- proposed variant id when possible;
- match score;
- match reason.

## Excluded rows

Rows excluded by V1 keywords should become candidates only if they are still commercially useful for future support, for example coffrets.

Suggested behavior:

- `coffret`, `set`, `duo`, `trio`: candidate with `needs_review` and reason `excluded_set_or_bundle`;
- body products such as `gel douche`, `body lotion`, `deodorant`: `rejected_not_perfume` unless site strategy says otherwise.

## Report fields

Add or update import report fields:

```json
{
  "candidates_created": 10,
  "candidates_updated": 5,
  "candidates_rejected_not_perfume": 3,
  "candidates_ignored_existing_status": 2
}
```

## Tests

Add tests for:

- unmatched fragrance creates candidate;
- duplicate import updates candidate instead of duplicating;
- fuzzy review range creates proposed product suggestion;
- rejected candidate is not recreated as pending;
- excluded body product is rejected or marked according to rule;
- coffret/set becomes review candidate, not offer.

## Acceptance criteria

- unmatched fragrance rows create candidates;
- duplicate imports do not create uncontrolled duplicates;
- rejected/ignored statuses are preserved;
- candidates include human-readable match reason;
- candidates contain enough parsed data for future admin review;
- no public product is created;
- no editorial product field is overwritten.

## PR description must include

- candidate deduplication strategy;
- status transition behavior;
- test results;
- report example;
- known limitations;
- next recommended task: PR07 cron/systemd and operational reports.
