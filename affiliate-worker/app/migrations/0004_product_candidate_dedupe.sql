ALTER TABLE product_match_candidates
ADD COLUMN IF NOT EXISTS dedupe_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_match_candidates_advertiser_dedupe
    ON product_match_candidates(advertiser_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_product_match_candidates_proposed_perfume
    ON product_match_candidates(proposed_perfume_id);
