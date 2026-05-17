# CODEX_START — Affiliate System

## Role

You are Codex implementing the Mes Fragrances affiliate system.

This repository is the implementation repository. It is not only a documentation repository.

## Repository policy

`stephanerey/mes-fragrances` is the canonical implementation repository for the affiliate system.

Codex must implement new source code, migrations, tests, Docker assets, and deployment helpers in this repository, starting from the PRD.

The current repository state is documentation-only:

- no worker code exists yet;
- no migrations exist yet;
- no import pipeline exists yet;
- no CIS integration exists yet.

Implement from scratch, following the PRD.

## Required reading order

Before implementing any code, read:

1. `AGENTS.md`
2. `docs/prd/affiliate-system/START_HERE.md`
3. `docs/prd/affiliate-system/PROJECT_PROFILE.md`
4. `docs/prd/affiliate-system/04_requirements/functional_requirements.md`
5. `docs/prd/affiliate-system/04_requirements/non_functional_requirements.md`
6. `docs/prd/affiliate-system/06_domain/affiliate_domain_rules.md`
7. `docs/prd/affiliate-system/06_domain/matching_rules.md`
8. `docs/prd/affiliate-system/10_architecture/system_architecture.md`
9. `docs/prd/affiliate-system/10_architecture/docker_runtime.md`
10. `docs/prd/affiliate-system/10_architecture/implementation_conventions.md`
11. `docs/prd/affiliate-system/10_architecture/secrets_strategy.md`
12. `docs/prd/affiliate-system/20_data/database_schema.md`
13. `docs/prd/affiliate-system/20_data/awin_feed_mapping.md`
14. `docs/prd/affiliate-system/20_data/migration_plan.md`
15. the relevant file under `docs/prd/affiliate-system/codex_tasks/`

## Execution workflow

Implement exactly one PRD slice at a time.

Default first task:

```text
PR01_worker_docker_skeleton.md
```

Do not implement later PR slices unless explicitly requested.

## Branch and PR policy

For each task:

1. create a dedicated branch;
2. keep changes scoped to the task;
3. add or update tests;
4. update PRD docs if implementation decisions change project truth;
5. open a GitHub Pull Request;
6. do not merge your own PR.

## Do-not rules

- Do not implement the worker inside the CIS container.
- Do not expose the worker publicly.
- Do not commit `.env` files or secrets.
- Do not log API tokens, feed keys, database credentials, or signed download URLs.
- Do not create public catalog products automatically from advertiser feeds.
- Do not overwrite existing editorial product fields without validation.
- Do not guess the CIS database schema. Inspect it first.
- Do not collapse multiple roadmap PRs into one large PR.

## Server inspection rule

Before any task touching deployment, Docker Compose integration, or existing CIS database tables, fill or update:

```text
docs/prd/affiliate-system/00_environment/vps_inventory.md
```

If the VPS/CIS environment differs from the PRD assumptions, update the PRD or state the deviation in the PR description.
