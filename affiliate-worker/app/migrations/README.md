# Affiliate Worker Migrations

PR04 uses explicit SQL files plus a small Python runner.

Structure:

- `0001_affiliate_foundation.sql`: additive affiliate schema foundation and Comas seed data.
- `0002_raw_staging_idempotency.sql`: raw staging deduplication safety index on
  `(advertiser_id, raw_hash)`.
- `0003_normalized_feed_items.sql`: additive normalized feed table for traceable,
  idempotent PR06 normalization output.

Rules:

- migrations are applied in filename order;
- applied versions are tracked in `affiliate_schema_migrations`;
- SQL files must be additive and reviewable;
- no secret values belong in SQL files.

Commands:

```bash
python -m app.main inspect-db
python -m app.main migrate-db --plan
python -m app.main migrate-db --dry-run
python -m app.main migrate-db
```

Backup before non-dry-run migration on the VPS:

```bash
mkdir -p ~/db_backups
chmod 700 ~/db_backups

docker exec mes-fragrances_cis-db-1 \
  pg_dump -U pilot -d pilot \
  > ~/db_backups/backup_before_affiliate_pr04_$(date +%Y%m%d_%H%M%S).sql
```

Rollback notes:

1. Preferred rollback: restore the backup taken immediately before `migrate-db`.
2. Because PR04 is additive-only, a manual rollback is also possible if no affiliate data has been used yet:
   drop tables in reverse dependency order:
   `external_product_mappings`,
   `product_match_candidates`,
   `offers`,
   `normalized_feed_items`,
   `raw_feed_items`,
   `feed_import_runs`,
   `affiliate_feeds`,
   `advertisers`,
   `affiliate_schema_migrations`.
3. Do not drop or alter existing CIS tables such as `perfumes` or `perfume_offers` during rollback.

PR04 intentionally defers `product_variants`.
The live CIS schema exposes `perfumes(id uuid, slug, name, brand, ...)`, so the new affiliate tables reference `perfumes(id)` only where that relationship is already confirmed and safe.

PR05 keeps raw staging additive-only as well. The extra index in `0002` prevents
uncontrolled duplicate `raw_feed_items` rows when a feed row has no stable
external IDs but its raw payload hash is identical to a previously imported row.

PR06 adds `normalized_feed_items` as a traceable, retry-safe layer between raw
staging and future matching/upsert logic. It stores normalized fragrance/filter
signals without touching `offers`, `product_match_candidates`,
`external_product_mappings`, `perfumes`, or `perfume_offers`.
