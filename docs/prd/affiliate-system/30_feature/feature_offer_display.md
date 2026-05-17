# Feature — Offer Display

## Goal

Display active affiliate offers on product pages in CIS.

## V1 scope

Show offers for a product when at least one active offer is matched.

Minimum display:

- advertiser name;
- product title or variant label;
- price;
- delivery cost when available;
- total price when available;
- CTA button;
- last price update or last seen timestamp.

## Query logic

Preferred query logic:

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

When the page is for a specific variant, prefer `product_variant_id`.

## Link rendering

Offer links should use:

```html
<a href="..." rel="sponsored nofollow" target="_blank">Voir l'offre</a>
```

When click tracking is implemented, the link should point to:

```text
/offers/click/{offer_id}
```

## Sorting policy

Initial sorting:

1. in stock first when stock is known;
2. lowest total price first;
3. advertiser priority as tie-breaker.

Future sorting may consider:

- commission;
- EPC;
- conversion rate;
- advertiser reliability;
- campaign strategy.

## Empty state

If no active offer exists, the product page should not display a broken offer block.

Optional future behavior:

- show “offres bientôt disponibles” only if useful;
- collect interest metrics.

## Acceptance criteria

- product page loads normally with zero offers;
- product page shows active offers when present;
- inactive offers are hidden;
- affiliate links use sponsored/nofollow attributes;
- display does not expose raw tracking or API data;
- the website remains functional if worker tables are empty.