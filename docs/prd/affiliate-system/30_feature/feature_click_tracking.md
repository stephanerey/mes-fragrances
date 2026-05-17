# Feature — Click Tracking

## Status

Future phase. Not required for the first feed import PR.

## Goal

Track outbound affiliate clicks before redirecting visitors to advertiser URLs.

## Route concept

```text
/offers/click/{offer_id}
```

The route should:

1. validate the offer exists and is active;
2. generate a click reference;
3. store the click event;
4. redirect to the affiliate URL.

## Click reference

Suggested format:

```text
mf_{product_id}_{variant_id}_{offer_id}_{short_random}
```

The exact format must fit Awin `clickref` constraints when implemented.

## Stored fields

- offer id;
- advertiser id;
- product id;
- product variant id;
- click reference;
- campaign;
- page URL;
- user agent;
- hashed IP if legally acceptable;
- timestamp.

## Privacy

Do not store raw IP addresses unless explicitly required and legally reviewed.

Prefer hashing or anonymization.

## Campaign values

Initial campaign values:

```text
product_page_best_offer
product_page_other_offers
homepage_deal
search_results
newsletter
```

## Acceptance criteria

- click route redirects correctly;
- inactive offers do not redirect silently;
- click event is stored once;
- generated click reference can be reconciled with future Awin transaction imports;
- no raw secrets are exposed in redirect logs.