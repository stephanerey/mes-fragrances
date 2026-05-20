# Codex Task PR06 — Normalization and Fragrance Filtering in Pipeline

## Goal

Convert raw staged Awin feed rows into normalized internal feed items and identify which rows are actionable fragrance rows.

This PR connects the preprocessing logic validated in PR03 to the raw staging/import pipeline from PR05.

## Branch

```text
feat/normalization-fragrance-filtering
```

## Prerequisites

- PR03 Awin preprocessing report merged.
- PR04 database migrations merged.
- PR05 raw staging import merged.

## Scope

Implement:

- text normalization utilities;
- HTML entity decoding;
- accent removal;
- whitespace/punctuation normalization;
- price parsing;
- currency normalization;
- category normalization;
- brand fallback extraction when no clean brand column exists;
- concentration parsing;
- volume parsing;
- exclusion keyword detection;
- normalized feed item representation;
- fragrance actionable filter;
- report counters integrated into import reports.

## Out of scope

Do not implement:

- fuzzy product matching;
- offer upsert;
- product candidate creation;
- public catalog product creation;
- front-end display.

## Input

Use raw staged rows from `raw_feed_items.raw_payload`.

The raw payload may come from:

- local CSV import;
- automatic Awin feed download.

## Output

Preferred implementation option:

- add a `normalized_feed_items` table if useful for traceability;
- or compute normalized rows during pipeline processing and write report output.

If adding a table, document the schema in the PR and update `20_data/database_schema.md`.

Minimum normalized fields:

```text
raw_feed_item_id
advertiser_id
network
network_product_id
merchant_product_id
title
normalized_title
description
brand
normalized_brand
category
merchant_category
price
currency
image_url
affiliate_url
merchant_url
ean
gtin
mpn
in_stock
stock_status
delivery_cost
concentration
volume_ml
is_fragrance
is_excluded
exclusion_reasons
missing_required_columns
missing_recommended_columns
```

## Fragrance filter V1

A row is actionable in V1 when:

```text
category_name == Fragrance
```

or a clearly equivalent normalized category is detected.

Rows outside the fragrance category may be normalized and reported, but must not become offers in this PR.

## Exclusion rule V1

Rows containing these terms should not auto-match or create offers later without review:

```text
coffret
set
duo
trio
tester
testeur
recharge
refill
gel douche
shower gel
lait corps
body lotion
déodorant
deodorant
diffuseur
bougie
candle
```

In PR06, only detect/report exclusions. Do not make matching decisions yet.

## Required tests

Add tests for:

- `normalize_text`;
- accent removal;
- HTML entity decoding;
- price parsing from `search_price`, `display_price`, `store_price`;
- concentration parsing;
- volume parsing;
- category filter;
- exclusion keyword detection;
- missing column report.

## Acceptance criteria

- normalization utilities are tested;
- fragrance rows are identified;
- non-fragrance rows are not actionable;
- exclusions are detected and reported;
- missing desired/required columns are reported;
- no offers are created;
- no product candidates are created;
- no catalog product is created.

## PR description must include

- normalized fields implemented;
- parsing examples covered by tests;
- report sample;
- known limitations;
- next recommended task: PR07 matching and offer upsert.
