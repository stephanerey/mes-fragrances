CREATE TABLE IF NOT EXISTS normalized_feed_items (
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
    exclusion_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_required_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_recommended_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    normalized_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(raw_feed_item_id)
);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_advertiser
    ON normalized_feed_items(advertiser_id);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_network_product_id
    ON normalized_feed_items(network_product_id);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_merchant_product_id
    ON normalized_feed_items(merchant_product_id);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_normalized_brand
    ON normalized_feed_items(normalized_brand);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_normalized_title
    ON normalized_feed_items(normalized_title);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_is_fragrance
    ON normalized_feed_items(is_fragrance);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_is_excluded
    ON normalized_feed_items(is_excluded);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_volume_ml
    ON normalized_feed_items(volume_ml);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_concentration
    ON normalized_feed_items(concentration);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_ean
    ON normalized_feed_items(ean);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_gtin
    ON normalized_feed_items(gtin);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_upc
    ON normalized_feed_items(upc);

CREATE INDEX IF NOT EXISTS idx_normalized_feed_items_mpn
    ON normalized_feed_items(mpn);
