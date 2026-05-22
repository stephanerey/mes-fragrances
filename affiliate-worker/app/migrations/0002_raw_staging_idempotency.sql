CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_feed_items_advertiser_raw_hash
    ON raw_feed_items(advertiser_id, raw_hash);
