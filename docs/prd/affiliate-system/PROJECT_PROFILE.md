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
3. Feed staging
4. Normalization
5. Product and variant matching
6. Offers upsert
7. Product candidate workflow
8. Cron / scheduler integration
9. Logs and import reports
10. Future click and transaction tracking

## First advertiser

- name: Perfumerias Comas FR
- network: Awin
- merchant id: `105475`
- feed id: `97867`
- initial feed format: CSV

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

1. Add worker Docker skeleton and configuration.
2. Add database migrations for affiliate tables.
3. Add raw feed import for Comas CSV.
4. Add normalization and fragrance filtering.
5. Add matching and offer upsert.
6. Add product candidates.
7. Add cron/systemd integration and logs.
8. Add front-end offer display in CIS.
9. Add click tracking.
10. Add Awin transaction/performance import.