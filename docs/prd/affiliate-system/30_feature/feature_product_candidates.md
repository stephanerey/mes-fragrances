# Feature — Product Candidates

## Goal

Capture unmatched but potentially relevant fragrance feed rows for manual review.

## Why this matters

Advertiser feeds may contain valid perfumes that are missing from the site catalog, but they may lack editorial data such as:

- olfactory family;
- notes;
- gender;
- concentration details;
- SEO description;
- clean brand information.

Therefore they must not become public products automatically.

## Candidate creation conditions

Create or update a candidate when:

- the feed row passes fragrance filtering;
- no confident product/variant match is found;
- the row is not clearly excluded by keyword/category;
- the item has a usable title and affiliate URL.

## Candidate fields

A candidate should store:

- advertiser id;
- raw feed item id;
- candidate brand;
- candidate name;
- concentration;
- volume;
- category;
- image URL;
- candidate URL;
- proposed product id when fuzzy match exists;
- proposed variant id when fuzzy match exists;
- match score;
- match reason;
- status;
- enrichment payload.

## Review statuses

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

## Admin workflow target

V1 may only create database candidates and reports.

A later admin UI should allow Eva to:

- review candidates;
- accept as existing product/variant;
- create a new variant;
- create a new product draft;
- reject false positives;
- lock external mappings.

## Acceptance criteria

- unmatched fragrance rows create candidates;
- duplicate imports update existing candidates rather than creating uncontrolled duplicates;
- rejected candidates are not recreated as pending on every import;
- candidate reasons are understandable by a human;
- no public product page is created automatically.