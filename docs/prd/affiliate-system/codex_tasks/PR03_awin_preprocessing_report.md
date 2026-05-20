# Codex Task PR03 — Awin Feed Preprocessing Report

## Goal

Measure the real downloaded Awin/Comas feed quality before implementing database staging, matching or offers.

This PR must answer whether the feed contains enough data for reliable matching and offer automation.

## Branch

```text
feat/awin-preprocessing-report
```

## Prerequisite

PR02 Awin feed discovery/download must be merged.

## Scope

Implement a preprocessing/reporting mode that parses a downloaded or local feed and reports:

- total rows;
- rows by `category_name`;
- rows where `category_name == Fragrance`;
- rows with usable product name;
- rows with affiliate URL;
- rows with valid price;
- rows with `brand_name`;
- rows with EAN/UPC/MPN/GTIN;
- rows with stock fields;
- rows with delivery fields;
- rows with usable image fields;
- rows with category path fields;
- rows with parsed volume;
- rows with parsed concentration;
- rows excluded by keyword: coffret, tester, refill, body product, etc.;
- estimated rows suitable for matching.

## Out of scope

Do not implement:

- database migrations;
- raw DB staging;
- offer upsert;
- fuzzy matching;
- product candidates;
- CIS integration.

## Required commands

Suggested command:

```bash
python -m app.main preprocess-feed --path /data/feeds/comas.csv.gz --advertiser 105475 --feed-id 97867
```

Or, if integrated with Awin download:

```bash
python -m app.main import-feeds --network awin --preprocess-only --advertiser 105475 --feed-id 97867
```

## Metrics to report

Minimum JSON report fields:

```json
{
  "status": "success",
  "rows_total": 7018,
  "category_counts": {
    "Fragrance": 2691
  },
  "rows_fragrance": 2691,
  "rows_with_brand_name": 0,
  "rows_with_any_identifier": 0,
  "rows_with_ean": 0,
  "rows_with_gtin": 0,
  "rows_with_mpn": 0,
  "rows_with_stock_status": 0,
  "rows_with_delivery_cost": 0,
  "rows_with_volume_ml": 0,
  "rows_with_concentration": 0,
  "rows_excluded_set_or_bundle": 0,
  "rows_excluded_body_product": 0,
  "estimated_matchable_rows": 0,
  "missing_required_columns": [],
  "missing_robust_matching_columns": []
}
```

## Parsing rules

Reuse or introduce tested utilities for:

- text normalization;
- price parsing;
- category normalization;
- concentration parsing;
- volume parsing;
- exclusion keyword detection.

This PR may implement these as preprocessing utilities, but must not yet create DB offers/candidates.

## Decision gate

After PR03, the PR description must state whether the feed is suitable for automated matching.

Minimum decision points:

```text
brand_name coverage: high/medium/low
identifier coverage: high/medium/low
volume parsing coverage: high/medium/low
concentration parsing coverage: high/medium/low
stock coverage: high/medium/low
offer URL/price coverage: high/medium/low
```

If coverage is poor, the PR must recommend whether to:

- adjust Awin selected columns;
- rely more on manual mapping;
- delay fuzzy matching;
- add additional enrichment steps.

## Tests

Add tests for:

- category counts;
- brand coverage;
- identifier coverage;
- price parsing;
- volume parsing;
- concentration parsing;
- exclusion counts;
- gzip/local CSV input.

## Acceptance criteria

- preprocessing report runs on local fixture;
- preprocessing report runs on downloaded Awin feed if credentials are available;
- report quantifies real feed quality;
- no DB mutations occur;
- no offers/candidates/products are created;
- report contains enough evidence to proceed or adjust Awin feed configuration.

## PR description must include

- report example;
- feed quality measurements from the real Comas feed if run on VPS;
- missing/available column summary;
- recommendation on whether to proceed to DB staging/migrations;
- next recommended task: PR04 database migrations.
