# Rollback Plan — Affiliate System

## Documentation PR rollback

This first PR is documentation-only. Rollback is simply reverting the documentation commit or closing the PR.

## Implementation rollback principles

Future implementation PRs must document rollback at PR level.

## Database rollback

Before production migrations:

1. create database backup;
2. store backup location in deployment notes;
3. apply migration;
4. verify website pages;
5. verify worker tables.

Example PostgreSQL backup:

```bash
pg_dump "$DATABASE_URL" > backup_before_affiliate_$(date +%Y%m%d_%H%M%S).sql
```

## Worker rollback

If the worker fails after deployment:

1. disable cron/systemd timer;
2. stop running worker container if needed;
3. keep existing offer tables untouched;
4. inspect latest import run;
5. fix and rerun dry-run first.

## Offer display rollback

If front-end offer rendering causes issues:

1. disable the offer block feature flag if available;
2. hide offers in template;
3. keep database tables untouched;
4. restore previous CIS container if needed.

## Data safety

Do not delete affiliate tables as rollback once real click or conversion history exists.

Prefer disabling features and preserving data.
