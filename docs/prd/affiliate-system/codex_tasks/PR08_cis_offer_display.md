# Codex Task PR08 — CIS Offer Display

## Goal

Display active affiliate offers on Mes Fragrances product pages through CIS without breaking pages that have no offers.

## Branch

```text
feat/cis-offer-display
```

## Prerequisites

- PR01 worker skeleton merged.
- PR02 database migrations merged.
- PR03 local CSV staging import merged.
- PR04 normalization/fragrance filtering merged.
- PR05 matching/offer upsert merged.
- PR06 product candidates merged.
- PR07 operational reports merged or at least worker tables populated in dev.
- CIS front-end structure inspected and documented in `00_environment/vps_inventory.md`.

## Scope

Implement:

- backend query/helper to retrieve active offers for a product or variant;
- front-end offer block on product pages;
- empty-state safe behavior;
- sorting by stock and total price;
- sponsored/nofollow link attributes;
- basic styling consistent with the site;
- tests or manual verification steps appropriate to CIS.

## Out of scope

Do not implement:

- click tracking redirect route; direct affiliate links are acceptable until PR09;
- transaction import;
- admin candidate review UI;
- automatic product publication.

## Query behavior

For product page display, retrieve active offers using product id first:

```sql
SELECT *
FROM offers
WHERE product_id = :product_id
  AND active = true
ORDER BY
  CASE WHEN in_stock IS true THEN 0 ELSE 1 END,
  total_price ASC,
  advertiser_id ASC;
```

When the page corresponds to a specific variant, prefer variant-level query:

```sql
SELECT *
FROM offers
WHERE product_variant_id = :product_variant_id
  AND active = true
ORDER BY
  CASE WHEN in_stock IS true THEN 0 ELSE 1 END,
  total_price ASC,
  advertiser_id ASC;
```

Adapt table/field names if implementation differs, but preserve behavior.

## Display fields

Minimum visible fields:

- advertiser name;
- variant label or offer title;
- price;
- delivery cost when available;
- total price when available;
- stock indicator when available;
- CTA button;
- last price update or last seen timestamp.

## Link behavior

Until PR09 click tracking exists, render direct affiliate URLs with:

```html
rel="sponsored nofollow"
target="_blank"
```

Do not expose raw tracking credentials or API keys.

## Empty state

If no active offers exist:

- product page must render normally;
- do not show a broken component;
- do not show placeholder pricing unless intentionally designed.

## Sorting rule V1

1. in-stock offers first when known;
2. lowest total price first;
3. advertiser priority if implemented;
4. advertiser id/name as stable tie-breaker.

## Performance

Do not add expensive per-page queries without indexes.

Use existing indexes or add indexes in a migration if needed.

## Acceptance criteria

- product page renders with zero offers;
- product page renders with one offer;
- product page renders with multiple offers sorted correctly;
- inactive offers are hidden;
- links have `rel="sponsored nofollow"`;
- page does not expose raw payload or secrets;
- display is resilient if optional fields are null.

## Validation

Run relevant CIS build/test commands after inspecting the app.

Manual checks:

- product with no offers;
- product with active offers;
- product with inactive offers only;
- offer with missing delivery cost;
- offer with unknown stock.

## PR description must include

- files/templates modified;
- query or helper added;
- screenshots if practical;
- manual validation results;
- known limitations;
- next recommended task: PR09 click tracking.
