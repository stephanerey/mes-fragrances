# Affiliate Domain Rules

## Domain objects

### Advertiser

An advertiser is a merchant or shop connected through an affiliate network.

Example:

```text
Perfumerias Comas FR
```

### Feed

A feed is a product data source exposed by an advertiser through an affiliate network.

An advertiser may expose multiple feeds.

### Catalog product

A catalog product is the editorial perfume entity displayed on `mes-fragrances.com`.

It may include information that is not available in advertiser feeds:

- olfactory family;
- fragrance notes;
- gender;
- product type;
- editorial description;
- SEO fields;
- internal images;
- publication status.

### Product variant

A product variant is a concrete purchasable version of a catalog product.

Examples:

```text
Chanel / Bleu de Chanel / Eau de Parfum / 100 ml
Dior / Sauvage / Eau de Toilette / 60 ml
Lancôme / La Vie Est Belle / Eau de Parfum / 50 ml
```

### Offer

An offer is an advertiser-provided commercial opportunity to buy a product or variant.

An offer contains:

- advertiser;
- price;
- currency;
- affiliate URL;
- image URL;
- stock state if available;
- last seen timestamp;
- match status.

## Core invariant

A catalog product is not an offer.

A product variant is not an offer.

An offer should point to a product variant when possible.

Logical chain:

```text
brand -> product -> product_variant -> offer
```

## Publication rule

The system may automatically update offers.

The system must not automatically publish a new catalog product page without explicit validation.

## Editorial safety rule

Advertiser feeds must not overwrite existing editorial product fields automatically.

Fields requiring manual or controlled enrichment include:

- fragrance family;
- notes;
- gender when uncertain;
- SEO description;
- product long description;
- canonical image selection.

## Candidate rule

Unmatched fragrance feed rows should become product candidates, not public products.

A candidate may represent:

- an existing product with a new advertiser offer;
- an existing product with a new variant;
- a truly new product;
- a non-fragrance false positive;
- a duplicate;
- a product outside the site editorial strategy.

## Offer lifecycle

1. First seen in feed: create or update active offer.
2. Seen again: update price, URL, image, stock, timestamps.
3. Price changed: update `last_price_change_at`.
4. Missing once: keep active.
5. Missing for configured number of successful imports: mark inactive.
6. Seen again after inactive: reactivate and update `last_seen_at`.

## Multi-advertiser rule

The data model must support many advertisers from day one.

No implementation should hard-code Comas-specific behavior outside configuration or importer tests.

## Network abstraction rule

Awin is the first network, not the domain model.

Tables and code should preserve `network` fields to allow future networks.

## Tracking rule

Affiliate URLs should eventually be reached through internal redirects to support click tracking.

The public HTML links should use appropriate sponsored/nofollow attributes when rendered by CIS.

## Failure rule

If feed import fails:

- the website must keep serving existing active offers;
- the failed run must be logged;
- no partial corrupted state should be published;
- the next run must be able to retry safely.