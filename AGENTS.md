# AGENTS.md

## Repository expectations

- Read `docs/prd/affiliate-system/CODEX_START.md` before editing project-critical code.
- Then read `docs/prd/affiliate-system/START_HERE.md` and the relevant task under `docs/prd/affiliate-system/codex_tasks/`.
- For affiliate work, read the domain docs and the relevant feature spec before implementation.
- Keep changes scoped to the requested PR slice.
- Prefer updating existing files and patterns rather than introducing parallel structures.
- Update docs when implementation decisions change the project truth.

## Current repository state

This repository is the canonical implementation repository for `mes-fragrances.com` affiliate infrastructure.

Current state:

- documentation and PRD only;
- no worker code yet;
- no database migrations yet;
- no import pipeline yet.

Codex must implement source code here, starting from the task files in `docs/prd/affiliate-system/codex_tasks/`.

## How to work in this repository

Build command: defined per task until implementation files exist.

Test command: defined per task until implementation files exist.

Lint/static analysis command: defined per task until implementation files exist.

Deployment check: to be defined after inspecting the CIS Docker stack on the VPS and filling `docs/prd/affiliate-system/00_environment/vps_inventory.md`.

## Branch and PR policy

- Create one branch per PRD task.
- Open one Pull Request per task.
- Do not merge your own PR.
- Do not implement multiple roadmap PRs in one branch unless explicitly requested.

## Constraints and do-not rules

- Do not implement the affiliate worker inside the CIS container.
- Do not expose the affiliate worker through Caddy or public ports.
- Do not commit secrets, API keys, database passwords, or real `.env` files.
- Do not log Awin credentials or database credentials.
- Do not publish new catalog products automatically from advertiser feeds.
- Do not overwrite editorial product attributes from feeds without validation.
- Do not make Comas-specific behavior global business logic.
- Do not introduce a new architecture decision without updating the PRD.

## Done when

- requested behavior is implemented;
- relevant tests or validation commands pass;
- impacted docs are updated when needed;
- changed files and impacts are summarized clearly;
- acceptance criteria from the PRD slice are checked.

## Planning rule

For complex features, migrations, Docker/runtime changes, or work spanning several modules, use `docs/prd/affiliate-system/PLANS.md` and the relevant task file before implementation.
