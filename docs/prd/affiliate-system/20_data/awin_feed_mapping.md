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

The initial feed should not be imported directly into production offer tables.

Known issues:

- not limited to fragrances;
- some useful columns may be empty depending on feed export format;
- product title must be parsed and normalized;
- brand may not be available as a clean column in the current export;
- EAN/GTIN may not be available in the current export;
- stock state may not be available in the current export.

## Required staging approach

All rows must first go through raw staging:

```text
CSV row -> raw_feed_items.raw_payload -> normalized representation -> filtered item -> matched offer or candidate
```

## Expected source columns

Implementation must inspect the actual CSV header at runtime.

Common useful fields may include:

```text
aw_product_id
merchant_product_id
product_name
description
category_name
merchant_category
search_price
display_price
currency
merchant_image_url
aw_deep_link
merchant_deep_link
brand_name
ean
product_GTIN
mpn
in_stock
delivery_cost
```

The current feed may not contain all these columns.

## Mapping to raw_feed_items

```text
network              -> 'awin'
network_product_id   -> aw_product_id
merchant_product_id  -> merchant_product_id
raw_payload          -> full row as JSON
raw_hash             -> sha256 hash of normalized raw payload
```

## Mapping to normalized internal item

| Internal field | Preferred source | Fallback |
|---|---|---|
| title | `product_name` | name-like column |
| description | `description` | empty |
| category | `category_name` | merchant category parsing |
| merchant_category | `merchant_category` | empty |
| price | `search_price` | parse `display_price` |
| currency | `currency` | `EUR` |
| image_url | `merchant_image_url` | image-like column |
| affiliate_url | `aw_deep_link` | `aw_image_url` or configured deep link field |
| merchant_url | `merchant_deep_link` | empty |
| brand | `brand_name` | parsed from title/category/manual map |
| ean | `ean` | empty |
| gtin | `product_GTIN` | empty |
| mpn | `mpn` | empty |
| stock | `in_stock` | null |
| delivery_cost | `delivery_cost` | null |

## Filtering rule V1

Actionable rows for V1:

```text
category_name == Fragrance
```

Rows outside this category may be stored raw but must not create active offers in V1.

## Download strategy

The worker should eventually use Awin feed discovery to identify downloadable feeds and avoid unnecessary downloads when the remote feed did not change.

For the first implementation slice, it is acceptable to support a local CSV import mode for the provided Comas feed.

## Local CSV import mode

V1 importer should support:

```bash
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv
```

This allows deterministic development and testing before live API integration.

## Live Awin mode

Later command:

```bash
python -m app.main import-feeds --network awin
```

## Security

Do not commit Awin credentials.

Do not store feed download URLs containing API keys in plain text unless required by the integration and protected appropriately.

## Validation report

Every import report must include the parsed CSV header and missing expected columns.
