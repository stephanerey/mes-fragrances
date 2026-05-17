# AGENTS.override.md — Affiliate System PRD

## Local subtree rules

This subtree contains the source-of-truth PRD for the affiliate system.

Before implementing affiliate code, read:

1. `START_HERE.md`
2. `PROJECT_PROFILE.md`
3. `04_requirements/functional_requirements.md`
4. `06_domain/affiliate_domain_rules.md`
5. `06_domain/matching_rules.md`
6. `10_architecture/system_architecture.md`
7. `20_data/database_schema.md`
8. the relevant file under `30_feature/`

## Local architecture rules

- Worker is separate from CIS.
- Product, variant and offer are distinct domain objects.
- Raw feed staging is mandatory before business logic.
- Ambiguous matches become candidates.
- New public catalog products require validation.

## Local docs rule

If code implementation changes a domain invariant, matching rule, migration strategy, or runtime assumption, update this PRD.