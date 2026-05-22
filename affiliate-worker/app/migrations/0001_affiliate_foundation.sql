CREATE TABLE IF NOT EXISTS advertisers (
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
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(network, network_advertiser_id)
);

CREATE TABLE IF NOT EXISTS affiliate_feeds (
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
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(network, network_feed_id)
);

CREATE INDEX IF NOT EXISTS idx_affiliate_feeds_advertiser_active
    ON affiliate_feeds(advertiser_id, active);

CREATE TABLE IF NOT EXISTS feed_import_runs (
    id BIGSERIAL PRIMARY KEY,
    feed_id BIGINT NOT NULL REFERENCES affiliate_feeds(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    source_file_sha256 TEXT,
    rows_total INTEGER NOT NULL DEFAULT 0,
    rows_filtered INTEGER NOT NULL DEFAULT 0,
    rows_matched INTEGER NOT NULL DEFAULT 0,
    rows_candidates INTEGER NOT NULL DEFAULT 0,
    rows_errors INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_feed_import_runs_feed_status
    ON feed_import_runs(feed_id, status, started_at DESC);

CREATE TABLE IF NOT EXISTS raw_feed_items (
    id BIGSERIAL PRIMARY KEY,
    import_run_id BIGINT NOT NULL REFERENCES feed_import_runs(id) ON DELETE CASCADE,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    network TEXT NOT NULL,
    network_product_id TEXT,
    merchant_product_id TEXT,
    raw_payload JSONB NOT NULL,
    raw_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(advertiser_id, network_product_id, merchant_product_id, raw_hash)
);

CREATE INDEX IF NOT EXISTS idx_raw_feed_items_import_run
    ON raw_feed_items(import_run_id);

CREATE TABLE IF NOT EXISTS offers (
    id BIGSERIAL PRIMARY KEY,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    perfume_id UUID REFERENCES perfumes(id) ON DELETE SET NULL,
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
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_price_change_at TIMESTAMPTZ,
    missed_imports INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    match_status TEXT NOT NULL DEFAULT 'unmatched',
    match_score NUMERIC(5, 2),
    match_method TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(advertiser_id, network_product_id, merchant_product_id)
);

CREATE INDEX IF NOT EXISTS idx_offers_perfume_active_total_price
    ON offers(perfume_id, active, total_price);

CREATE INDEX IF NOT EXISTS idx_offers_advertiser
    ON offers(advertiser_id);

CREATE TABLE IF NOT EXISTS product_match_candidates (
    id BIGSERIAL PRIMARY KEY,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    raw_feed_item_id BIGINT REFERENCES raw_feed_items(id) ON DELETE SET NULL,
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
    enrichment_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_match_candidates_status
    ON product_match_candidates(status, created_at DESC);

CREATE TABLE IF NOT EXISTS external_product_mappings (
    id BIGSERIAL PRIMARY KEY,
    advertiser_id BIGINT NOT NULL REFERENCES advertisers(id) ON DELETE CASCADE,
    network_product_id TEXT,
    merchant_product_id TEXT,
    perfume_id UUID NOT NULL REFERENCES perfumes(id) ON DELETE CASCADE,
    confidence NUMERIC(5, 2) NOT NULL DEFAULT 100,
    locked BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(advertiser_id, network_product_id, merchant_product_id)
);

CREATE INDEX IF NOT EXISTS idx_external_product_mappings_perfume
    ON external_product_mappings(perfume_id);

INSERT INTO advertisers (
    network,
    network_advertiser_id,
    name,
    country_code,
    currency,
    awin_feed_id,
    priority,
    active,
    metadata,
    updated_at
)
VALUES (
    'awin',
    '105475',
    'Perfumerias Comas FR',
    'FR',
    'EUR',
    '97867',
    100,
    TRUE,
    jsonb_build_object(
        'locale', 'fr_FR',
        'seed_source', 'pr04',
        'pr03_validated_rows_total', 2702,
        'pr03_validated_header_count', 86,
        'pr03_recommendation', 'proceed_to_db_staging'
    ),
    NOW()
)
ON CONFLICT (network, network_advertiser_id)
DO UPDATE SET
    name = EXCLUDED.name,
    country_code = EXCLUDED.country_code,
    currency = EXCLUDED.currency,
    awin_feed_id = EXCLUDED.awin_feed_id,
    priority = EXCLUDED.priority,
    active = EXCLUDED.active,
    metadata = advertisers.metadata || EXCLUDED.metadata,
    updated_at = NOW();

WITH seed_advertiser AS (
    SELECT id
    FROM advertisers
    WHERE network = 'awin'
      AND network_advertiser_id = '105475'
)
INSERT INTO affiliate_feeds (
    advertiser_id,
    network,
    network_feed_id,
    language,
    active,
    metadata,
    updated_at
)
SELECT
    seed_advertiser.id,
    'awin',
    '97867',
    'fr_FR',
    TRUE,
    jsonb_build_object(
        'locale', 'fr_FR',
        'currency', 'EUR',
        'expected_format', 'csv',
        'expected_delimiter', 'comma',
        'expected_compression', 'gzip',
        'last_validated_rows_total', 2702,
        'last_validated_header_count', 86,
        'pr03_recommendation', 'proceed_to_db_staging'
    ),
    NOW()
FROM seed_advertiser
ON CONFLICT (network, network_feed_id)
DO UPDATE SET
    advertiser_id = EXCLUDED.advertiser_id,
    language = EXCLUDED.language,
    active = EXCLUDED.active,
    metadata = affiliate_feeds.metadata || EXCLUDED.metadata,
    updated_at = NOW();
