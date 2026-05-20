# PROJECT_PROFILE — Affiliate System

## Product name

Mes Fragrances affiliate system.

## System type

Backend data pipeline plus website integration.

## Runtime context

- VPS provider: OVH
- OS: Ubuntu
- deployment: Docker / Docker Compose
- existing platform: CIS CMS
- reverse proxy: Caddy managed by CIS stack
- database: existing CIS database, assumed PostgreSQL until verified on server

## Implementation principle

The affiliate feed system must be implemented as a separate Docker worker. CIS must consume clean database tables but must not own the feed ingestion logic.

## Primary modules

1. Affiliate worker
2. Awin integration
3. Feed discovery/download
4. Feed preprocessing and quality report
5. Feed staging
6. Normalization
7. Product and variant matching
8. Offers upsert
9. Product candidate workflow
10. Cron / scheduler integration
11. Logs and import reports
12. Future click and transaction tracking

## First advertiser

- name: Perfumerias Comas FR
- network: Awin
- merchant id: `105475`
- feed id: `97867`
- initial feed format: CSV/gzip in production, local CSV fixture for tests

## Core design decision

A catalog product is not the same object as an advertiser offer.

The expected logical chain is:

```text
brand -> product -> product_variant -> offer
```

An offer usually points to a precise variant, such as:

```text
Lancôme / La Vie Est Belle / Eau de Parfum / 50 ml
```

not only to:

```text
Lancôme / La Vie Est Belle
```

## Versioning policy

All important domain and architecture decisions must be reflected in this PRD. Chat messages are not source of truth.

## Initial PR strategy

The first implementation steps must validate the real Awin feed before database and matching work.

1. Add worker Docker skeleton and configuration.
2. Validate Awin feed discovery/download.
3. Produce Awin feed preprocessing and quality report.
4. Add database migrations for affiliate tables.
5. Add raw staging import for Comas CSV/Awin feed.
6. Add normalization and fragrance filtering in the pipeline.
7. Add matching and offer upsert.
8. Add product candidates.
9. Add cron/systemd integration and operational reports.
10. Add front-end offer display in CIS.
11. Add click tracking.
12. Add Awin transaction/performance import.

## Gate before matching

Do not proceed to matching/offer automation until PR03 measures the real Awin feed quality:

- column coverage;
- fragrance row count;
- brand coverage;
- identifier coverage: EAN/UPC/MPN/GTIN;
- volume parsing coverage;
- concentration parsing coverage;
- price and URL coverage;
- stock and delivery coverage;
- exclusion rates for coffrets/testers/body products.
