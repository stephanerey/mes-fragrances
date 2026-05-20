# Codex Task PR12 — Awin Transactions and Performance

## Goal

Import Awin transaction/performance data and prepare revenue-oriented reporting for advertiser and offer optimization.

## Branch

```text
feat/awin-transactions-performance
```

## Prerequisites

- PR01 worker skeleton merged.
- PR04 database migrations merged.
- PR10 CIS offer display merged.
- PR11 click tracking merged.
- Awin credentials configured on VPS.

## Scope

Implement:

- Awin transaction API client;
- transaction import command;
- click reference reconciliation where possible;
- advertiser performance import or report command;
- transaction persistence tables or documented schema extension;
- reporting fields for revenue, commission, conversion and EPC;
- tests with mocked Awin responses;
- safe secret handling.

## Out of scope

Do not implement:

- complex BI dashboard;
- automatic commercial ranking changes without review;
- payout/accounting system;
- attribution beyond available Awin/click_ref data.

## Commands

Suggested commands:

```bash
python -m app.main import-awin-transactions --from-date YYYY-MM-DD --to-date YYYY-MM-DD
python -m app.main import-awin-performance --from-date YYYY-MM-DD --to-date YYYY-MM-DD
python -m app.main affiliate-report --period 30d
```

Exact names may be adapted, but document them.

## Transaction fields

Persist or report fields such as:

```text
network
network_transaction_id
advertiser_id
order_ref
click_ref
transaction_date
validation_status
commission_amount
sale_amount
currency
product_id when reconciled
product_variant_id when reconciled
offer_id when reconciled
campaign when reconciled
raw_payload
created_at
updated_at
```

## Reconciliation

Use `click_ref` from PR11 where available.

If no click reference is available:

- keep the transaction raw/imported;
- mark reconciliation status as unmatched;
- do not discard the transaction.

## Advertiser performance

Capture or report, where available:

- clicks;
- transactions;
- conversion rate;
- commission;
- sale amount;
- EPC;
- validation/rejection metrics.

## Reporting outputs

Minimum report:

```json
{
  "period": "30d",
  "transactions_total": 0,
  "transactions_reconciled": 0,
  "commission_total": 0,
  "sale_total": 0,
  "top_advertisers": [],
  "top_products": [],
  "top_campaigns": []
}
```

## Security

- Do not log Awin API tokens.
- Do not commit API responses containing sensitive user/customer data.
- Store only fields needed for affiliate analysis.
- Keep raw payloads if useful, but avoid storing unnecessary personal data.

## Tests

Add tests with mocked API responses for:

- transaction import success;
- duplicate transaction idempotence;
- click_ref reconciliation;
- unmatched transaction persistence;
- advertiser performance parsing;
- API failure handling;
- token not present in logs.

## Acceptance criteria

- Awin transaction import command exists;
- transactions are persisted or reported idempotently;
- click_ref reconciliation works when possible;
- unmatched transactions are preserved;
- performance report can be generated;
- no secrets are logged;
- no personal data is stored unnecessarily;
- implementation remains network-aware and can be extended later.

## PR description must include

- APIs/endpoints used;
- date range behavior;
- schema changes;
- reconciliation logic;
- report example;
- privacy/security notes;
- validation/test results.
