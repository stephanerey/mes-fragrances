# Functional Requirements — Affiliate System

## FR-001 — Advertiser registry

The system must store affiliate advertisers independently from offers and feeds.

Minimum advertiser fields:

- internal id;
- affiliate network;
- network advertiser id;
- advertiser name;
- country code;
- currency;
- active flag;
- priority;
- metadata JSON.

## FR-002 — Feed registry

The system must store advertiser feeds independently from advertisers.

A feed belongs to one advertiser. An advertiser may have multiple feeds.

Minimum feed fields:

- internal id;
- advertiser id;
- network;
- network feed id;
- feed name;
- language;
- vertical;
- last checked timestamp;
- last successful import timestamp;
- active flag;
- metadata JSON.

## FR-003 — Import run tracking

Every import execution must create an import run record.

The run must track:

- start timestamp;
- end timestamp;
- status;
- source checksum when available;
- total rows;
- filtered rows;
- matched rows;
- candidate rows;
- error rows;
- error message when failed.

## FR-004 — Raw feed persistence

The system must store raw feed rows before applying business logic.

Raw storage must preserve the original payload in JSON form and include enough identifiers to trace the row back to advertiser, feed, and import run.

## FR-005 — Feed normalization

The system must normalize feed rows into a clean internal representation.

Normalization must handle at least:

- HTML entity decoding;
- case folding;
- accent removal;
- punctuation normalization;
- price parsing;
- category parsing;
- fragrance concentration parsing;
- volume parsing;
- basic exclusion keywords.

## FR-006 — Fragrance filtering

The first import must only create actionable offers for perfume/fragrance products.

For the initial Comas feed, category filtering must prioritize rows where `category_name` is `Fragrance`.

Non-fragrance rows may still be stored in raw staging but must not become public offers.

## FR-007 — Product variant model

The system must support product variants.

A product variant represents a concrete purchasable form of a perfume, for example:

```text
Dior / Sauvage / Eau de Parfum / 100 ml
```

Offers should target product variants when possible.

## FR-008 — Offer upsert

The system must insert or update offers from matched feed items.

Offer upsert must be idempotent. Re-importing the same feed must not duplicate offers.

Offer fields must include at least:

- advertiser id;
- product id when matched;
- product variant id when matched;
- network product id;
- merchant product id;
- title;
- price;
- currency;
- delivery cost when available;
- affiliate URL;
- image URL;
- stock status when available;
- active flag;
- match status;
- match score;
- raw payload.

## FR-009 — Price change tracking

When an existing offer changes price, the system must update the price and set `last_price_change_at`.

## FR-010 — Missing offer handling

Offers not seen in recent successful imports must not be deleted immediately.

They must be marked inactive only after a configurable number of missed imports, default `3`.

## FR-011 — Product candidates

Unmatched feed items that look like valid fragrance products must create or update product candidates.

Candidates must support review statuses such as:

- pending;
- needs_review;
- accepted_existing_variant;
- accepted_new_variant;
- accepted_new_product;
- rejected_not_perfume;
- rejected_duplicate;
- ignored.

## FR-012 — Manual mappings

The system must support locked manual mappings between external advertiser products and internal products/variants.

Locked mappings must take priority over fuzzy matching.

## FR-013 — Daily automation

The worker must support execution from cron or systemd timer on the Ubuntu host.

The first version may be triggered with:

```bash
docker compose run --rm affiliate-worker python -m app.main import-feeds
```

## FR-014 — Import report

Each worker execution must produce a readable report containing:

- advertiser;
- feed id;
- rows total;
- rows filtered;
- offers matched;
- candidates created or updated;
- offers updated;
- offers deactivated;
- errors.

## FR-015 — Future click tracking

The system should support future internal redirect tracking for affiliate clicks.

The front-end should eventually link to an internal route such as:

```text
/offers/click/{offer_id}
```

The route records the click and redirects to the advertiser affiliate URL.