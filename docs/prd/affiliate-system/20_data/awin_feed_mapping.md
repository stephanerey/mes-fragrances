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

The Awin Create-a-Feed UI allows selecting additional columns before generating the feed download URL. The production worker must use a configured Awin download URL with the selected column set, then validate the actual downloaded header at runtime.

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

Awin's Product Feed List Download gives publishers a CSV list of accessible feeds, including feed id, last update/import time and download URL. The worker must use this list as the default production discovery mechanism.

The feed URL contains a `columns/...` segment. The application must not hard-code the incomplete CSV header from the manually downloaded test file. Instead, it must use a configured/generated Awin download URL containing the selected column set.

## Feed column configuration rule

Column selection is controlled by the Awin feed/download URL generated through Awin Create-a-Feed.

Recommendation for this project:

```text
Select all available product data columns where possible.
```

Reason:

- raw staging preserves the full payload;
- later matching needs `brand_name`, `ean`, `upc`, `mpn`, `product_GTIN`, stock fields, delivery fields and category path fields;
- unused fields can be ignored after staging;
- having too few fields is more damaging than having extra fields.

If Awin limits the selected column count or if the feed becomes too large, use the priority groups below.

The worker must:

- store feed metadata without exposing secrets;
- parse the actual downloaded header;
- compare it with the required and recommended lists below;
- include missing columns in the import report;
- avoid logging full signed/API-key URLs.

## Awin export properties

Use these settings for the Comas feed unless there is a proven reason to change them:

```text
format: csv
delimiter: comma (,)
compression: gzip
```

The generated URL may include segments similar to:

```text
format/csv/delimiter/%2C/compression/gzip
```

The worker must support gzip-compressed CSV downloads.

## Required columns for raw staging and basic offers

Required for reliable raw staging and basic offer creation:

```text
aw_product_id
merchant_product_id
product_name
aw_deep_link
merchant_image_url
description
merchant_category
search_price
merchant_name
merchant_id
category_name
category_id
currency
display_price
data_feed_id
```

At least one stable external id must be available:

```text
aw_product_id or merchant_product_id
```

At least one affiliate/merchant link must be available:

```text
aw_deep_link or merchant_deep_link
```

At least one price source must be available:

```text
search_price or display_price or store_price
```

If both `aw_product_id` and `merchant_product_id` are missing, the worker may still stage the row using `raw_hash`, but it must report the row as missing stable external ids and must not auto-match it.

## Required columns for robust perfume matching

These fields are available in the Awin selectable columns shown by the operator and must be selected for production when available:

```text
brand_name
brand_id
ean
upc
mpn
product_GTIN
parent_product_id
merchant_product_category_path
merchant_product_second_category
merchant_product_third_category
product_type
keywords
specifications
in_stock
stock_quantity
stock_status
is_for_sale
web_offer
pre_order
valid_from
valid_to
delivery_cost
delivery_time
large_image
merchant_thumb_url
alternate_image
alternate_image_two
alternate_image_three
alternate_image_four
commission_group
```

If any of these are absent from a downloaded feed, the worker must not fail raw staging, but it must include them in `missing_recommended_columns` and lower matching confidence when relevant.

Identifier fields have special importance:

```text
ean
upc
mpn
product_GTIN
parent_product_id
```

If present, they must be used before fuzzy matching.

## Recommended selected columns

These are the columns visible in the Awin Create-a-Feed UI and recommended for this project.

### Generic / default

```text
aw_deep_link
product_name
aw_product_id
merchant_product_id
merchant_image_url
description
merchant_category
search_price
```

### Recommended

```text
merchant_name
merchant_id
category_name
category_id
aw_image_url
currency
store_price
delivery_cost
merchant_deep_link
language
last_updated
display_price
data_feed_id
```

### Product details

```text
brand_name
brand_id
colour
product_short_description
specifications
condition
product_model
model_number
dimensions
keywords
product_type
```

### Product category

```text
commission_group
merchant_product_category_path
merchant_product_second_category
merchant_product_third_category
```

### Price

```text
rrp_price
saving
savings_percent
base_price
base_price_amount
base_price_text
product_price_old
```

### Delivery and conditions

```text
delivery_restrictions
delivery_weight
warranty
terms_of_contract
delivery_time
```

### Availability

```text
in_stock
stock_quantity
valid_from
valid_to
is_for_sale
web_offer
pre_order
stock_status
size_stock_status
size_stock_amount
```

### Images

```text
merchant_thumb_url
large_image
alternate_image
aw_thumb_url
alternate_image_two
alternate_image_three
alternate_image_four
```

### Ratings / evaluations

```text
reviews
average_rating
rating
number_available
```

### Custom fields

```text
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

### Identifiers

```text
ean
isbn
upc
mpn
parent_product_id
product_GTIN
```

### Other

```text
basket_link
```

## Minimal column URL for current manual selection

The screenshots show a currently selected column set similar to:

```text
aw_deep_link,product_name,aw_product_id,merchant_product_id,merchant_image_url,description,merchant_category,search_price,merchant_name,merchant_id,category_name,category_id,aw_image_url,currency,store_price,delivery_cost,merchant_deep_link,language,last_updated,display_price,data_feed_id
```

This is enough for raw staging and basic offer creation, but it is not acceptable as the final production column set because it misses robust matching fields such as:

```text
brand_name
ean
upc
mpn
product_GTIN
parent_product_id
in_stock
stock_quantity
stock_status
merchant_product_category_path
large_image
merchant_thumb_url
alternate_image*
commission_group
keywords
product_type
specifications
```

## Preferred production column URL

Codex should document or generate the selected Awin URL with all recommended selected columns above.

The production URL should include a `columns/` segment containing all selected column names, comma-separated and URL-encoded by Awin.

Do not commit an actual URL containing API keys.

Store only a redacted example such as:

```text
https://productdata.awin.com/datafeed/download/apikey/<redacted>/language/fr/fid/97867/id/0/hasEnhancedFeeds/0/columns/<url-encoded-columns>/format/csv/delimiter/%2C/compression/gzip/adultcontent/1
```

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
| category_id | `category_id` | empty |
| merchant_category | `merchant_category` | `merchant_product_category_path` |
| price | `search_price` | `display_price`, `store_price` |
| store_price | `store_price` | null |
| display_price | `display_price` | null |
| rrp_price | `rrp_price` | null |
| saving | `saving` | null |
| savings_percent | `savings_percent` | null |
| currency | `currency` | `EUR` |
| image_url | `large_image` | `merchant_image_url`, `aw_image_url` |
| thumbnail_url | `merchant_thumb_url` | `aw_thumb_url` |
| alternate_images | `alternate_image*` | empty |
| affiliate_url | `aw_deep_link` | configured deep link field |
| merchant_url | `merchant_deep_link` | empty |
| advertiser_name | `merchant_name` | advertisers table |
| advertiser_network_id | `merchant_id` | configured advertiser id |
| brand | `brand_name` | parsed from title/category/manual map |
| brand_id | `brand_id` | empty |
| ean | `ean` | empty |
| gtin | `product_GTIN` | empty |
| upc | `upc` | empty |
| mpn | `mpn` | empty |
| parent_product_id | `parent_product_id` | empty |
| stock | `in_stock` | infer from `stock_status`, null |
| stock_quantity | `stock_quantity` | null |
| stock_status | `stock_status` | empty |
| is_for_sale | `is_for_sale` | null |
| delivery_cost | `delivery_cost` | null |
| delivery_time | `delivery_time` | empty |
| commission_group | `commission_group` | empty |
| keywords | `keywords` | empty |
| product_type | `product_type` | empty |
| specifications | `specifications` | empty |
| custom_fields | `custom_1`..`custom_9` | empty |

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
- required columns present/missing;
- robust matching columns present/missing;
- recommended columns present/missing;
- source file checksum;
- remote Last Imported when available;
- whether the feed was downloaded or skipped;
- row counts by category where practical;
- feed format, delimiter and compression detected/used.
