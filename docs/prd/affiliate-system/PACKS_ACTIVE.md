# PACKS_ACTIVE

This project PRD uses a local project-specific pack rather than modifying the upstream PRD template.

## Active local pack

### affiliate_feed_pipeline

Purpose: describe the advertiser feed ingestion system, product matching workflow, offer update logic, and operational constraints.

Imported/adapted content:

- `40_active_packs/affiliate_feed_pipeline/README.md`
- `40_active_packs/affiliate_feed_pipeline/awin.md`
- `40_active_packs/affiliate_feed_pipeline/matching.md`
- `40_active_packs/affiliate_feed_pipeline/worker.md`

Local adaptations:

- first implementation targets Awin and Perfumerias Comas FR;
- architecture must remain network-agnostic enough for future affiliate networks;
- feed worker must run outside the CIS container;
- product candidates require validation before public catalog publication.

## Codex templates

The repository also includes adapted Codex instructions:

- root `AGENTS.md`
- `docs/prd/affiliate-system/AGENTS.override.md`
- `docs/prd/affiliate-system/PLANS.md`

## Rule

Pack files are guidance. The final project truth is the filled PRD under `docs/prd/affiliate-system/`.