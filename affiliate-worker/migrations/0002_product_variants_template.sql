-- 0002_product_variants_template.sql
-- This migration is intentionally not auto-applied by default.
-- It depends on the actual CIS product table name and primary key.
--
-- Apply only after running `inspect-db` and confirming that the product table is named `products`
-- with a BIGINT-compatible `id` primary key.
--
-- If CIS uses another table name, adapt this migration before applying.

CREATE TABLE IF NOT EXISTS product_variants (
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

CREATE INDEX IF NOT EXISTS idx_product_variants_product
ON product_variants(product_id);

CREATE INDEX IF NOT EXISTS idx_product_variants_ean
ON product_variants(ean)
WHERE ean IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_product_variants_gtin
ON product_variants(gtin)
WHERE gtin IS NOT NULL;
