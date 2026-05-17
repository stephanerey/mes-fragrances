# Awin Feed Mapping

## Initial feed

Initial feed analyzed during planning:

```text
105475-97867-fr_FR-Perfumerias_Comas_FR_PDF.csv
```

Known characteristics:

- advertiser: Perfumerias Comas FR;
- network: Awin;
- merchant id: `105475`;
- data feed id: `97867`;
- locale: `fr_FR`;
- currency: EUR;
- total rows: approximately 7018;
- fragrance rows: approximately 2691;
- category mix includes fragrance, skincare, haircare, make-up and others.

## Important feed quality observations

The initially provided CSV was incomplete because it did not include all potentially available Awin columns.

Do not treat missing fields in that CSV as proof that the advertiser cannot provide them.

Fields such as `brand_name`, `ean`, `product_GTIN`, `mpn`, `in_stock`, `stock_status`, `delivery_cost`, `large_image`, and other vertical fields may be available if the Awin feed/download URL is configured with the appropriate columns.

The implementation must therefore:

1. support the provided CSV only as a local deterministic development input;
2. implement automatic Awin feed discovery/download as the production path;
3. validate the downloaded feed header at runtime;
4. report missing expected columns;
5. continue safely with fallbacks where allowed;
6. fail or mark the import as incomplete where required columns are missing.

## Awin feed access model

Awin product feeds are not manually uploaded into this application in production.

The worker must fetch them automatically.

Expected production flow:

```text
Awin Product Feed List Download
        |
        v
list accessible feeds with Last Imported and download URL
        |
        v
filter advertiser 105475 / feed 97867 or configured advertisers
        |
        v
compare remote Last Imported with local last_success_at / metadata
        |
        v
download feed only when changed
        |
        v
raw staging -> normalization -> matching -> offers/candidates
```

Awin's Product Feed List Download gives publishers a CSV list of accessible feeds, including feed id, last update/import time and a download URL. The worker must use this list as the default production discovery mechanism.

The feed URL contains a `columns/...` segment. The application should not hard-code the incomplete CSV header from the manually downloaded test file. Instead, it must use a configured/generated Awin download URL containing the desired column set.

## Feed column configuration rule

Column selection is controlled by the Awin feed/download URL, typically generated/configured through Awin Create-a-Feed.

The operator should configure the feed in Awin with all useful columns selected where available.

The worker must:

- store the selected/download URL metadata without exposing secrets;
- parse the actual downloaded header;
- compare it with the desired column list below;
- include missing columns in the import report;
- avoid logging full signed/API-key URLs.

## Desired columns

Desired production columns:

```text
aw_product_id
merchant_product_id
product_name
description
category_name
category_id
merchant_category
merchant_product_category_path
search_price
display_price
rrp_price
saving
savings_percent
currency
merchant_image_url
aw_image_url
merchant_thumb_url
large_image
alternate_image
aw_deep_link
merchant_deep_link
merchant_name
merchant_id
language
last_updated
brand_name
brand_id
ean
isbn
upc
mpn
product_GTIN
parent_product_id
in_stock
stock_quantity
stock_status
is_for_sale
web_offer
pre_order
delivery_cost
delivery_time
commission_group
keywords
product_type
specifications
custom_1
custom_2
custom_3
custom_4
custom_5
custom_6
custom_7
custom_8
custom_9
```

## Required columns

Required for raw staging:

```text
aw_product_id or merchant_product_id
product_name
aw_deep_link or merchant_deep_link
search_price or display_price
currency
category_name or merchant_category
```

If both `aw_product_id` and `merchant_product_id` are missing, the worker must still stage the row using `raw_hash`, but it must report the row as missing stable external ids.

## Required staging approach

All rows must first go through raw staging:

```text
CSV row -> raw_feed_items.raw_payload -> normalized representation -> filtered item -> matched offer or candidate
```

## Mapping to raw_feed_items

```text
network              -> 'awin'
network_product_id   -> aw_product_id
merchant_product_id  -> merchant_product_id
raw_payload          -> full row as JSON
raw_hash             -> sha256 hash of canonical JSON row
```

## Mapping to normalized internal item

| Internal field | Preferred source | Fallback |
|---|---|---|
| title | `product_name` | name-like column |
| description | `description` | `product_short_description`, empty |
| category | `category_name` | merchant category parsing |
| merchant_category | `merchant_category` | `merchant_product_category_path` |
| price | `search_price` | parse `display_price` |
| rrp_price | `rrp_price` | null |
| currency | `currency` | `EUR` |
| image_url | `large_image` | `merchant_image_url`, `aw_image_url` |
| affiliate_url | `aw_deep_link` | configured deep link field |
| merchant_url | `merchant_deep_link` | empty |
| brand | `brand_name` | parsed from title/category/manual map |
| brand_id | `brand_id` | empty |
| ean | `ean` | empty |
| gtin | `product_GTIN` | empty |
| upc | `upc` | empty |
| mpn | `mpn` | empty |
| parent_product_id | `parent_product_id` | empty |
| stock | `in_stock` | infer from `stock_status`, null |
| stock_status | `stock_status` | empty |
| delivery_cost | `delivery_cost` | null |
| commission_group | `commission_group` | empty |

## Filtering rule V1

Actionable rows for V1:

```text
category_name == Fragrance
```

Rows outside this category may be stored raw but must not create active offers in V1.

## Local CSV import mode

Local CSV import remains useful for deterministic development and tests:

```bash
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv
```

The local CSV may be incomplete and must not define the production column contract.

## Live Awin mode

Production command target:

```bash
python -m app.main import-feeds --network awin
```

Expected behavior:

1. download the Awin product feed list using `AWIN_PRODUCT_FEED_API_KEY`;
2. filter active advertiser/feed records from `affiliate_feeds`;
3. compare remote `Last Imported` with local metadata;
4. download only changed feeds;
5. save raw downloaded feed file under `/data/feeds/`;
6. run the same staging/import pipeline as local CSV mode;
7. write a report including header, missing columns and download decision.

## Security

Do not commit Awin credentials.

Do not store feed download URLs containing API keys in plain text unless required by the integration and protected appropriately.

Never log full download URLs with API keys.

## Validation report

Every import report must include:

- parsed CSV header;
- desired columns present/missing;
- required columns present/missing;
- source file checksum;
- remote Last Imported when available;
- whether the feed was downloaded or skipped;
- row counts by category where practical.
