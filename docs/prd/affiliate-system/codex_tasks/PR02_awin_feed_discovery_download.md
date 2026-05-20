# Codex Task PR02 — Awin Feed Discovery and Download Smoke Test

## Goal

Validate the real Awin feed access path before implementing database staging, matching or offers.

This PR must prove that the worker can discover and download the Comas feed automatically using Awin credentials, without relying on a manually uploaded CSV.

## Branch

```text
feat/awin-feed-discovery-download
```

## Prerequisite

PR01 worker Docker skeleton must be merged.

## Scope

Implement:

- Awin configuration loading;
- Awin product feed list download client;
- parsing of the feed list CSV;
- advertiser/feed filtering for `105475` / `97867`;
- remote `Last Imported` extraction when available;
- safe redaction of download URLs containing API keys;
- gzip CSV download support;
- CSV header parsing;
- required/recommended column presence report;
- download-only / dry-run mode;
- JSON report under `/data/reports/`;
- tests with mocked Awin responses.

## Out of scope

Do not implement:

- database migrations;
- raw staging into DB;
- normalization beyond header and basic row count;
- matching;
- offer creation;
- product candidates;
- CIS integration.

## Required commands

Suggested commands:

```bash
python -m app.main awin-list-feeds --dry-run
python -m app.main awin-download-feed --advertiser 105475 --feed-id 97867 --dry-run
```

Alternative command names are acceptable if clearly documented.

A combined command is acceptable:

```bash
python -m app.main import-feeds --network awin --download-only --dry-run
```

## Expected behavior

The worker must:

1. read `AWIN_PRODUCT_FEED_API_KEY` from environment;
2. request/download the Awin product feed list;
3. parse available feeds;
4. locate feed `97867` for advertiser `105475` where possible;
5. read feed metadata, including `Last Imported` when available;
6. retrieve or validate the feed download URL;
7. download the gzip CSV when not in metadata-only mode;
8. decompress it;
9. parse the CSV header;
10. compare the header against `20_data/awin_feed_mapping.md`;
11. write a report;
12. never log API keys or full signed URLs.

## Column validation

The report must include:

```json
{
  "required_columns_present": [],
  "required_columns_missing": [],
  "robust_matching_columns_present": [],
  "robust_matching_columns_missing": [],
  "recommended_columns_present": [],
  "recommended_columns_missing": []
}
```

Fields like `brand_name`, `ean`, `upc`, `mpn`, `product_GTIN`, `in_stock`, `stock_status`, `large_image`, and `merchant_product_category_path` must be treated as expected production fields when available.

## Report example

```json
{
  "status": "success",
  "network": "awin",
  "advertiser_id": "105475",
  "feed_id": "97867",
  "feed_found": true,
  "remote_last_imported": "...",
  "downloaded": true,
  "compression": "gzip",
  "format": "csv",
  "delimiter": ",",
  "header_count": 72,
  "rows_sampled": 10,
  "download_url_redacted": true,
  "missing_required_columns": [],
  "missing_robust_matching_columns": []
}
```

## Security

- Never log the product feed API key.
- Never log a full feed download URL if it contains an API key.
- Reports may include a redacted URL only.
- Do not commit downloaded feeds.
- Do not commit `.env`.

## Tests

Add tests for:

- feed list parsing;
- finding feed by advertiser/feed id;
- redacting download URLs;
- gzip CSV header parsing;
- missing column reporting;
- API failure handling;
- missing credentials handling.

Use mocked HTTP responses.

## Acceptance criteria

- worker can discover the Comas feed from Awin feed list;
- worker can download/open gzip CSV in smoke-test mode;
- header validation works;
- report includes column coverage;
- no database writes occur;
- no secrets are logged;
- PR remains limited to Awin feed discovery/download.

## PR description must include

- commands implemented;
- report example;
- Awin feed metadata observed, with secrets redacted;
- column coverage summary;
- validation/test results;
- next recommended task: PR03 Awin preprocessing report.
