# Codex Task PR09 — Click Tracking

## Goal

Track outbound affiliate clicks before redirecting visitors to advertiser URLs.

## Branch

```text
feat/affiliate-click-tracking
```

## Prerequisites

- PR01 worker skeleton merged.
- PR02 database migrations merged.
- PR05 matching/offer upsert merged.
- PR08 CIS offer display merged.
- Website routing mechanism inspected and documented in `00_environment/vps_inventory.md`.

## Scope

Implement:

- internal click redirect route;
- click reference generation;
- affiliate click persistence;
- safe redirect to affiliate URL;
- campaign parameter support;
- offer display update to use internal click route;
- tests or manual verification.

## Out of scope

Do not implement:

- Awin transaction import;
- revenue dashboards;
- advertiser performance scoring;
- advanced attribution models.

## Route

Preferred route:

```text
/offers/click/{offer_id}
```

Optional query parameter:

```text
?campaign=product_page_best_offer
```

## Redirect flow

1. receive request;
2. validate offer exists;
3. validate offer is active;
4. generate `click_ref`;
5. store click event;
6. redirect to affiliate URL.

Inactive/missing offers must not redirect silently.

## Click reference

Suggested format:

```text
mf_{product_id}_{variant_id}_{offer_id}_{short_random}
```

Adapt if Awin `clickref` length or character constraints require it.

## Database

Use or create `affiliate_clicks` table as specified in `20_data/database_schema.md`.

Stored fields:

```text
offer_id
advertiser_id
product_id
product_variant_id
click_ref
campaign
page_url
user_agent
ip_hash
created_at
```

## Privacy

Do not store raw IP addresses unless explicitly approved.

Prefer hashing/anonymization.

If hashing IPs, use a server-side salt from environment variables, not committed to Git.

## Campaign values

Initial values:

```text
product_page_best_offer
product_page_other_offers
homepage_deal
search_results
newsletter
unknown
```

## Offer display update

After this PR, product page offer links should point to the internal route rather than directly to `affiliate_url`.

The final redirect target remains the advertiser affiliate URL.

## Failure behavior

If click persistence fails:

- prefer fail-closed for missing/inactive offers;
- for active offers, decide whether to redirect anyway or show a clear error;
- document the chosen behavior in the PR description.

## Security

- Validate `offer_id` server-side.
- Do not allow arbitrary redirect URLs from request parameters.
- Redirect only to the stored affiliate URL for the offer.
- Do not expose raw affiliate URL in logs if it contains sensitive parameters.

## Tests

Add tests for:

- active offer redirects;
- inactive offer blocked;
- missing offer blocked;
- click event created;
- campaign stored;
- no arbitrary open redirect.

## Acceptance criteria

- click route works for active offers;
- click events are stored once per request;
- generated click reference is available for future transaction reconciliation;
- inactive/missing offers do not redirect silently;
- offer display uses internal click links;
- no raw secrets are logged;
- no open redirect vulnerability exists.

## PR description must include

- route implemented;
- click_ref format;
- privacy decision for IP/user-agent;
- validation/test results;
- known limitations;
- next recommended task: PR10 Awin transactions and performance.
