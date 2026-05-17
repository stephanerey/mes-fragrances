# PROJECT_INTAKE — Affiliate System

## Project

`mes-fragrances.com` is live and runs on CIS, an all-in-one CMS deployed in Docker on an OVH VPS running Ubuntu.

CIS includes:

- front-end with AI-based builder;
- administration back-end;
- database;
- Caddy reverse proxy.

The site currently contains more than 1500 perfume products in its database.

## Business context

Eva started affiliate partnerships through Awin. The first accepted advertiser is Perfumerias Comas FR.

A CSV product feed was downloaded from Awin with approximately 7000 products. The current feed contains mixed categories, including fragrances, skincare, haircare, make-up and other beauty products.

The affiliate system must automate feed ingestion and expose relevant offers on the website.

## Primary goal

Build a scalable affiliate infrastructure able to integrate many advertisers, keep prices up to date, and discover new products that may enrich the existing perfume catalog.

## Key input source

Initial advertiser feed:

- network: Awin
- advertiser: Perfumerias Comas FR
- merchant id: `105475`
- feed id: `97867`
- locale: `fr_FR`
- currency: EUR
- approximate rows: 7018
- fragrance rows: approximately 2691

## Main user stories

### Visitor

As a visitor, I want to see available merchant offers on a perfume page so I can buy the product from a partner retailer.

### Site owner

As the site owner, I want affiliate offers to be updated automatically so prices and availability remain fresh without manual work.

### Eva / administrator

As an administrator, I want unmatched advertiser products to appear as candidates so I can decide whether to map them to an existing product, create a variant, or add a new catalog product.

### Developer / Codex

As an implementation agent, I need a precise PRD, data model, and acceptance criteria so each implementation PR stays scoped and reviewable.

## Constraints

- Do not implement the feed worker inside the CIS container.
- Do not expose the worker publicly.
- Do not publish new products automatically without validation.
- Do not overwrite existing editorial product attributes automatically.
- Do not store API keys in source control.
- Do not log secrets.
- Keep imports idempotent.
- Keep the website available even if a feed import fails.

## Initial implementation target

The first implementation must support Awin and Perfumerias Comas FR, while keeping the architecture open for future advertisers and networks.