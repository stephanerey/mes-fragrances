# Mes Fragrances — Affiliate System PRD

## Purpose

This PRD defines the affiliate offer ingestion system for `mes-fragrances.com`.

The goal is to let Codex implement the system incrementally without relying on hidden chat context.

## Source template

This project PRD is inspired by `stephanerey/prd_template`:

- use a stable project PRD as the source of truth;
- keep Codex instructions explicit and versioned;
- split work into reviewable implementation slices;
- preserve domain rules in documentation, not only in code.

The global PRD template repository must not be modified for this project. This folder is the project-specific PRD instance.

## Reading order for humans and Codex

1. `PROJECT_INTAKE.md`
2. `PROJECT_PROFILE.md`
3. `PACKS_ACTIVE.md`
4. `04_requirements/functional_requirements.md`
5. `06_domain/affiliate_domain_rules.md`
6. `06_domain/matching_rules.md`
7. `10_architecture/system_architecture.md`
8. `20_data/database_schema.md`
9. `20_data/awin_feed_mapping.md`
10. `30_feature/feature_affiliate_worker.md`
11. `90_quality/acceptance_tests.md`
12. `PLANS.md`

## Non-negotiable project rule

The PRD is the project truth. If implementation decisions change the design, update this PRD in the same PR or in a follow-up documentation PR.

## Current implementation strategy

The affiliate system must be implemented as a separate Docker worker, not inside the CIS container.

The worker is responsible for:

- discovering and downloading advertiser feeds;
- storing raw feed rows;
- normalizing product information;
- matching feed items to catalog products and variants;
- updating affiliate offers;
- creating review candidates for unmatched products;
- writing import reports and logs.

CIS remains responsible for rendering the website and reading clean database tables.