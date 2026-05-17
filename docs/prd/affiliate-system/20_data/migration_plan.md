# Migration Plan — Affiliate System

## Step 0 — Inspect existing CIS schema

Before writing migrations, Codex must inspect the live or development database schema.

Minimum checks:

```sql
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';
```

Identify existing tables for:

- products;
- brands;
- users/admin if relevant;
- current product attributes;
- existing slugs or SEO fields.

## Step 1 — Add isolated affiliate tables

Create these tables first because they should not modify existing product behavior:

- `advertisers`
- `affiliate_feeds`
- `feed_import_runs`
- `raw_feed_items`
- `offers`
- `product_match_candidates`
- `external_product_mappings`

## Step 2 — Add product variants

Create `product_variants` after confirming the existing product table name and primary key.

If the existing product table is not named `products`, adapt foreign keys accordingly.

## Step 3 — Add brand support if missing

If a usable brand table already exists, reuse it.

If not, add `brands` and decide how existing product brand fields map to it.

Do not migrate brand data blindly in the first PR unless the existing data is inspected and backed up.

## Step 4 — Add product columns only if needed

Optional product columns should be added only after schema inspection.

Potential additions:

- normalized name;
- slug;
- gender;
- fragrance family;
- enrichment status;
- metadata JSON.

## Step 5 — Add indexes

Indexes should support common queries:

- active offers by product;
- active offers by variant;
- offers by advertiser;
- candidates by status;
- import runs by feed/date.

## Step 6 — Seed first advertiser and feed

Seed:

```text
advertiser: Perfumerias Comas FR
network: awin
network_advertiser_id: 105475
network_feed_id: 97867
currency: EUR
active: true
```

## Step 7 — Rollback considerations

Because the first migration set creates isolated tables, rollback can drop affiliate tables if no production data must be preserved.

Once offers are used by the website, rollback must avoid losing click/revenue history.

## Step 8 — Backup rule

Before applying migrations to the VPS production database:

```bash
pg_dump "$DATABASE_URL" > backup_before_affiliate_$(date +%Y%m%d_%H%M%S).sql
```

Adapt the command if the DB is not PostgreSQL.

## Migration acceptance criteria

- migrations apply cleanly on an empty/dev database;
- migrations apply cleanly against the inspected CIS database;
- migration does not break existing product pages;
- no existing product rows are deleted;
- seed data for Comas exists;
- rollback notes are documented.