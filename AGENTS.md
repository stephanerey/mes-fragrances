# AGENTS.md

## Repository expectations

- Read `docs/prd/affiliate-system/START_HERE.md` before editing project-critical code.
- For affiliate work, read the domain docs and the relevant feature spec before implementation.
- Keep changes scoped to the requested PR slice.
- Prefer updating existing files and patterns rather than introducing parallel structures.
- Update docs when implementation decisions change the project truth.

## Current repository state

This repository starts as the documentation and implementation home for `mes-fragrances.com` affiliate infrastructure.

The first major feature is the affiliate feed pipeline for Awin and Perfumerias Comas FR.

## How to work in this repository

Build command: to be defined when implementation files are added.

Test command: to be defined when implementation files are added.

Lint/static analysis command: to be defined when implementation files are added.

Deployment check: to be defined after inspecting the CIS Docker stack on the VPS.

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

For complex features, migrations, Docker/runtime changes, or work spanning several modules, use `docs/prd/affiliate-system/PLANS.md` before implementation.
