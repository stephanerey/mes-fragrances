# Database Schema — Affiliate System

## Important note

The existing CIS database schema must be inspected before implementation.

The SQL below defines the target logical model. Names may be adapted to project conventions, but the domain structure must remain intact.

## advertisers

```sql
CREATE TABLE advertisers (
    id BIGSERIAL PRIMARY KEY,
    network TEXT NOT NULL,
    network_advertiser_id TEXT NOT NULL,
    name TEXT NOT NULL,
    country_code TEXT,
    currency TEXT,
    awin_feed_id TEXT,
    awin_feed_name TEXT,
    awin_membership_status TEXT,
    deeplink_enabled BOOLEAN,
    commission_min NUMERIC(10, 4),
    commission_max NUMERIC(10, 4),
    commission_type TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(network, network_advertiser_id)
);
```

## affiliate_feeds

```sql
CREATE TABLE affiliate_feeds (
    id BIGSERIAL PRIMARY KEY,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    network TEXT NOT NULL,
    network_feed_id TEXT NOT NULL,
    feed_name TEXT,
    language TEXT,
    vertical TEXT,
    download_url TEXT,
    last_imported_remote TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(network, network_feed_id)
);
```

## feed_import_runs

```sql
CREATE TABLE feed_import_runs (
    id BIGSERIAL PRIMARY KEY,
    feed_id BIGINT NOT NULL REFERENCES affiliate_feeds(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    source_file_sha256 TEXT,
    rows_total INTEGER DEFAULT 0,
    rows_filtered INTEGER DEFAULT 0,
    rows_matched INTEGER DEFAULT 0,
    rows_candidates INTEGER DEFAULT 0,
    rows_errors INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'
);
```

## raw_feed_items

```sql
CREATE TABLE raw_feed_items (
    id BIGSERIAL PRIMARY KEY,
    import_run_id BIGINT NOT NULL REFERENCES feed_import_runs(id) ON DELETE CASCADE,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    network TEXT NOT NULL,
    network_product_id TEXT,
    merchant_product_id TEXT,
    raw_payload JSONB NOT NULL,
    raw_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(advertiser_id, network_product_id, merchant_product_id, raw_hash)
);
```

## normalized_feed_items

```sql
CREATE TABLE normalized_feed_items (
    id BIGSERIAL PRIMARY KEY,
    raw_feed_item_id BIGINT NOT NULL REFERENCES raw_feed_items(id) ON DELETE CASCADE,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    feed_id BIGINT REFERENCES affiliate_feeds(id) ON DELETE SET NULL,
    network TEXT NOT NULL,
    network_product_id TEXT,
    merchant_product_id TEXT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    description TEXT,
    brand TEXT,
    normalized_brand TEXT,
    category TEXT,
    normalized_category TEXT,
    merchant_category TEXT,
    price NUMERIC(12, 2),
    currency TEXT,
    delivery_cost NUMERIC(12, 2),
    affiliate_url TEXT,
    merchant_url TEXT,
    image_url TEXT,
    ean TEXT,
    gtin TEXT,
    upc TEXT,
    mpn TEXT,
    in_stock BOOLEAN,
    stock_status TEXT,
    concentration TEXT,
    volume_ml NUMERIC(8, 2),
    is_fragrance BOOLEAN NOT NULL DEFAULT FALSE,
    is_excluded BOOLEAN NOT NULL DEFAULT FALSE,
    exclusion_reasons JSONB NOT NULL DEFAULT '[]',
    missing_required_columns JSONB NOT NULL DEFAULT '[]',
    missing_recommended_columns JSONB NOT NULL DEFAULT '[]',
    normalized_payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(raw_feed_item_id)
);
```

## brands

If the existing CIS database does not already have a brand table, create or adapt one.

```sql
CREATE TABLE brands (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    slug TEXT NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(slug)
);
```

## products

The current product table must be inspected and adapted. It should remain the editorial canonical product table.

Suggested fields if absent:

```sql
ALTER TABLE products
ADD COLUMN IF NOT EXISTS brand_id BIGINT REFERENCES brands(id),
ADD COLUMN IF NOT EXISTS normalized_name TEXT,
ADD COLUMN IF NOT EXISTS slug TEXT,
ADD COLUMN IF NOT EXISTS gender TEXT,
ADD COLUMN IF NOT EXISTS fragrance_family TEXT,
ADD COLUMN IF NOT EXISTS enrichment_status TEXT NOT NULL DEFAULT 'manual',
ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
```

## product_variants

```sql
CREATE TABLE product_variants (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    concentration TEXT,
    volume_ml NUMERIC(8, 2),
    variant_label TEXT,
    gtin TEXT,
    ean TEXT,
    mpn TEXT,
    normalized_variant_key TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(product_id, normalized_variant_key)
);
```

## offers

```sql
CREATE TABLE offers (
    id BIGSERIAL PRIMARY KEY,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
    product_variant_id BIGINT REFERENCES product_variants(id) ON DELETE SET NULL,
    network TEXT NOT NULL,
    network_product_id TEXT,
    merchant_product_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    price NUMERIC(12, 2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    delivery_cost NUMERIC(12, 2),
    total_price NUMERIC(12, 2) GENERATED ALWAYS AS (price + COALESCE(delivery_cost, 0)) STORED,
    affiliate_url TEXT NOT NULL,
    merchant_url TEXT,
    image_url TEXT,
    in_stock BOOLEAN,
    stock_status TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_price_change_at TIMESTAMPTZ,
    missed_imports INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    match_status TEXT NOT NULL DEFAULT 'unmatched',
    match_score NUMERIC(5, 2),
    match_method TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(advertiser_id, network_product_id, merchant_product_id)
);

CREATE INDEX idx_offers_product_variant_active ON offers(product_variant_id, active, total_price);
CREATE INDEX idx_offers_product_active ON offers(product_id, active, total_price);
CREATE INDEX idx_offers_advertiser ON offers(advertiser_id);
```

## external_product_mappings

```sql
CREATE TABLE external_product_mappings (
    id BIGSERIAL PRIMARY KEY,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    network_product_id TEXT,
    merchant_product_id TEXT,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_variant_id BIGINT REFERENCES product_variants(id) ON DELETE CASCADE,
    confidence NUMERIC(5, 2) NOT NULL DEFAULT 100,
    locked BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(advertiser_id, network_product_id, merchant_product_id)
);
```

## product_match_candidates

```sql
CREATE TABLE product_match_candidates (
    id BIGSERIAL PRIMARY KEY,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    raw_feed_item_id BIGINT REFERENCES raw_feed_items(id) ON DELETE SET NULL,
    dedupe_key TEXT,
    candidate_brand TEXT,
    candidate_name TEXT NOT NULL,
    candidate_concentration TEXT,
    candidate_volume_ml NUMERIC(8, 2),
    candidate_category TEXT,
    candidate_image_url TEXT,
    candidate_url TEXT,
    proposed_perfume_id UUID REFERENCES perfumes(id) ON DELETE SET NULL,
    match_score NUMERIC(5, 2),
    match_reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    source_count INTEGER NOT NULL DEFAULT 1,
    advertiser_count INTEGER NOT NULL DEFAULT 1,
    enrichment_payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_product_match_candidates_advertiser_dedupe
    ON product_match_candidates(advertiser_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;
```

## affiliate_clicks — future phase

```sql
CREATE TABLE affiliate_clicks (
    id BIGSERIAL PRIMARY KEY,
    offer_id BIGINT REFERENCES offers(id) ON DELETE SET NULL,
    advertiser_id BIGINT REFERENCES advertisers(id) ON DELETE SET NULL,
    product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
    product_variant_id BIGINT REFERENCES product_variants(id) ON DELETE SET NULL,
    click_ref TEXT NOT NULL,
    campaign TEXT,
    page_url TEXT,
    user_agent TEXT,
    ip_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_affiliate_clicks_offer ON affiliate_clicks(offer_id, created_at);
CREATE INDEX idx_affiliate_clicks_click_ref ON affiliate_clicks(click_ref);
```

## Migration rule

Codex must inspect the existing database schema before applying these names directly.

If CIS uses different naming conventions, adapt table names but preserve relationships and invariants.
