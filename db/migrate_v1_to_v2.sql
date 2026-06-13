-- =============================================================================
-- Card Ledger migration: v1 -> v2
-- Safe to run on an existing database with data. Idempotent.
--   * adds packs_opened (multi-day rips) and a 'partial' acquisition status
--   * adds tcgplayer_product_id + image_url to item
--   * upgrades allocate_box_cost() to prorate cost by packs opened
-- Run:  psql -d your_db -f migrate_v1_to_v2.sql
-- =============================================================================
BEGIN;

ALTER TABLE acquisition ADD COLUMN IF NOT EXISTS packs_opened integer
    CHECK (packs_opened IS NULL OR packs_opened >= 0);

ALTER TABLE item ADD COLUMN IF NOT EXISTS tcgplayer_product_id text;
ALTER TABLE item ADD COLUMN IF NOT EXISTS image_url            text;

-- Allow 'partial' status on a box that's mid-rip.
ALTER TABLE acquisition DROP CONSTRAINT IF EXISTS acquisition_status_check;
ALTER TABLE acquisition ADD  CONSTRAINT acquisition_status_check
    CHECK (status IN ('sealed','partial','opened','resold_sealed'));

CREATE OR REPLACE FUNCTION allocate_box_cost(p_acquisition_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_total_cost  numeric(12,2);
    v_packs_total integer;
    v_packs_open  integer;
    v_allocatable numeric(12,2);
    v_total_mv    numeric(12,2);
    v_n_items     integer;
BEGIN
    SELECT total_cost, packs_total, packs_opened
    INTO v_total_cost, v_packs_total, v_packs_open
    FROM acquisition WHERE acquisition_id = p_acquisition_id;

    SELECT COALESCE(SUM(market_value_at_open), 0), COUNT(*)
    INTO v_total_mv, v_n_items
    FROM item WHERE acquisition_id = p_acquisition_id;

    IF v_n_items = 0 THEN
        RETURN;
    END IF;

    IF v_packs_total IS NOT NULL AND v_packs_open IS NOT NULL AND v_packs_total > 0 THEN
        v_allocatable := v_total_cost * LEAST(v_packs_open, v_packs_total)::numeric / v_packs_total;
    ELSE
        v_allocatable := v_total_cost;
    END IF;

    IF v_total_mv > 0 THEN
        UPDATE item i
        SET cost_basis = ROUND(v_allocatable * COALESCE(i.market_value_at_open, 0) / v_total_mv, 2)
        WHERE i.acquisition_id = p_acquisition_id;
    ELSE
        UPDATE item i
        SET cost_basis = ROUND(v_allocatable / v_n_items, 2)
        WHERE i.acquisition_id = p_acquisition_id;
    END IF;
END;
$$;

COMMIT;
