-- =============================================================================
-- Card Collecting Ledger  --  PostgreSQL schema
-- =============================================================================
-- Tracks the money side of MTG / Weiss Schwarz collecting:
--   acquisition  -> every purchase (sealed box, pack, single, bulk lot)
--   item         -> every individual sellable unit derived from an acquisition
--   sale         -> every time an item leaves, with all the fees that eat margin
--
-- Design notes
--   * Box-level ROI is the source of truth. Per-card profit is derived by
--     allocating a box's cost across its pulls *weighted by market value*
--     (chase cards carry most of the cost), via allocate_box_cost().
--   * Generated columns compute roll-up totals automatically, so DBeaver shows
--     them without you doing arithmetic.
--   * Cross-table math (profit, ROI, holding period) lives in the v_* views.
--   * COMMENT ON statements populate DBeaver's column descriptions.
-- Run once:  psql -d your_db -f card_ledger_schema.sql
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ACQUISITIONS  (one row per purchase event)
-- ---------------------------------------------------------------------------
CREATE TABLE acquisition (
    acquisition_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_date   date        NOT NULL,
    description     text        NOT NULL,                 -- "Frieren Booster Box (WS, EN)"
    game            text        NOT NULL CHECK (game IN ('mtg','weiss','pokemon','other','mixed')),
    product_type    text        NOT NULL CHECK (product_type IN
                                    ('sealed_box','sealed_pack','bundle','single','bulk_lot','other')),
    set_code        text,                                 -- set / expansion identifier
    language        text        NOT NULL DEFAULT 'EN',    -- 'EN', 'JP', ...
    quantity        integer     NOT NULL DEFAULT 1 CHECK (quantity > 0),

    -- Sealed-product breakdown (NULL for singles) -> drives price-per-pack math
    packs_total     integer     CHECK (packs_total     IS NULL OR packs_total     > 0),
    cards_per_pack  integer     CHECK (cards_per_pack  IS NULL OR cards_per_pack  > 0),
    packs_opened    integer     CHECK (packs_opened    IS NULL OR packs_opened   >= 0), -- for multi-day rips

    -- Cost components, in the currency you actually paid
    purchase_price  numeric(12,2) NOT NULL CHECK (purchase_price >= 0),
    tax             numeric(12,2) NOT NULL DEFAULT 0 CHECK (tax >= 0),
    shipping_in     numeric(12,2) NOT NULL DEFAULT 0 CHECK (shipping_in >= 0),
    other_fees      numeric(12,2) NOT NULL DEFAULT 0 CHECK (other_fees >= 0),
    currency        text        NOT NULL DEFAULT 'USD',
    fx_rate_to_usd  numeric(14,6) NOT NULL DEFAULT 1 CHECK (fx_rate_to_usd > 0),

    -- All-in landed cost (native currency). Generated -> always correct.
    total_cost      numeric(12,2) GENERATED ALWAYS AS
                        (purchase_price + tax + shipping_in + other_fees) STORED,

    source          text,                                 -- vendor / store
    channel         text,                                 -- 'lgs','ebay','tcgplayer','japan_proxy',...
    status          text        NOT NULL DEFAULT 'sealed'
                                    CHECK (status IN ('sealed','partial','opened','resold_sealed')),
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  acquisition                IS 'One row per purchase event (box, pack, single, or bulk lot).';
COMMENT ON COLUMN acquisition.total_cost     IS 'All-in landed cost: purchase + tax + shipping_in + other_fees (native currency).';
COMMENT ON COLUMN acquisition.packs_total    IS 'Packs in a sealed product; powers price-per-pack views. NULL for singles.';
COMMENT ON COLUMN acquisition.packs_opened   IS 'Packs ripped so far; lets multi-day rips prorate cost. Equals packs_total when fully opened.';
COMMENT ON COLUMN acquisition.fx_rate_to_usd IS 'Multiply native amounts by this for USD reporting (e.g. JP product).';
COMMENT ON COLUMN acquisition.status         IS 'sealed = unopened, partial = mid-rip, opened = fully cracked, resold_sealed = flipped sealed.';

-- ---------------------------------------------------------------------------
-- 2. ITEMS  (one row per sellable unit: a card, or a sealed product to flip)
-- ---------------------------------------------------------------------------
CREATE TABLE item (
    item_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    acquisition_id      bigint NOT NULL REFERENCES acquisition(acquisition_id) ON DELETE CASCADE,
    kind                text   NOT NULL DEFAULT 'card' CHECK (kind IN ('card','sealed','bulk')),

    -- Identity
    name                text   NOT NULL,
    game                text   CHECK (game IS NULL OR game IN ('mtg','weiss','pokemon','other')),
    set_code            text,
    collector_number    text,
    variant             text,                              -- 'foil','showcase','SP','SSP', etc.
    language            text   NOT NULL DEFAULT 'EN',
    condition           text   CHECK (condition IS NULL OR condition IN
                                    ('NM','LP','MP','HP','DMG','sealed')),

    -- Grading (NULL unless graded)
    grader              text   CHECK (grader IS NULL OR grader IN ('PSA','BGS','CGC','TAG','SGC','other')),
    grade               numeric(4,1),                      -- 10, 9.5, ...
    subgrades           jsonb,                             -- {"centering":9.5,"corners":10,...}
    cert_number         text,
    grade_date          date,

    -- Costs
    cost_basis          numeric(12,2) DEFAULT 0,           -- set by allocate_box_cost() for box pulls
    grading_fee         numeric(12,2) NOT NULL DEFAULT 0 CHECK (grading_fee  >= 0),
    grading_ship        numeric(12,2) NOT NULL DEFAULT 0 CHECK (grading_ship >= 0),
    grading_extra       numeric(12,2) NOT NULL DEFAULT 0 CHECK (grading_extra>= 0), -- slab, reholder, etc.
    grading_total       numeric(12,2) GENERATED ALWAYS AS
                            (grading_fee + grading_ship + grading_extra) STORED,

    -- Valuation
    market_value_at_open numeric(12,2),                    -- snapshot when cracked (drives allocation + EV)
    market_value         numeric(12,2),                    -- current; refresh from a new scan export

    status              text   NOT NULL DEFAULT 'inventory'
                            CHECK (status IN ('inventory','listed','sold','keep','grading','lost')),
    grade_candidate     boolean NOT NULL DEFAULT false,    -- triage flag: "this should be graded"
    graded_value_est    numeric(12,2),                     -- optional est. slab value -> grading upside
    storage_location    text,                              -- e.g. a 3D-printed tray / binder slot
    tcgplayer_product_id text,                             -- from CSV 'Product ID'; for re-pricing
    image_url           text,                              -- from CSV 'Photo URL'; for the catalog site
    notes               text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_item_acquisition ON item(acquisition_id);
CREATE INDEX idx_item_status      ON item(status);

COMMENT ON TABLE  item                        IS 'One row per individual card (or a sealed product being flipped).';
COMMENT ON COLUMN item.cost_basis             IS 'Allocated share of the acquisition cost. Set by allocate_box_cost() for box pulls.';
COMMENT ON COLUMN item.grading_total          IS 'Total grading spend added to basis: fee + shipping + extras.';
COMMENT ON COLUMN item.market_value_at_open   IS 'Market value at the moment the box was opened; used for weighted cost allocation and box EV.';
COMMENT ON COLUMN item.market_value           IS 'Current market value; refresh periodically for unrealized P&L.';
COMMENT ON COLUMN item.status                 IS 'keep = personal collection (counts as value retained, not a sale).';

-- ---------------------------------------------------------------------------
-- 3. SALES  (one row per item sold)
-- ---------------------------------------------------------------------------
CREATE TABLE sale (
    sale_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id          bigint NOT NULL REFERENCES item(item_id) ON DELETE CASCADE,
    sale_date        date   NOT NULL,
    channel          text,                                  -- 'ebay','tcgplayer','lgs',...

    gross_price      numeric(12,2) NOT NULL CHECK (gross_price >= 0),  -- item price the buyer paid
    shipping_charged numeric(12,2) NOT NULL DEFAULT 0,                 -- shipping the buyer paid you
    marketplace_fee  numeric(12,2) NOT NULL DEFAULT 0,
    processing_fee   numeric(12,2) NOT NULL DEFAULT 0,
    promo_fee        numeric(12,2) NOT NULL DEFAULT 0,                 -- promoted listings / ads
    shipping_paid    numeric(12,2) NOT NULL DEFAULT 0,                 -- what shipping actually cost you
    supplies_cost    numeric(12,2) NOT NULL DEFAULT 0,                 -- mailer, toploader, sleeve

    -- What actually landed in your pocket. Generated -> always correct.
    net_proceeds     numeric(12,2) GENERATED ALWAYS AS
                        (gross_price + shipping_charged
                         - marketplace_fee - processing_fee - promo_fee
                         - shipping_paid - supplies_cost) STORED,

    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_sale_item ON sale(item_id);

COMMENT ON TABLE  sale              IS 'One row per item sold, capturing every cost that eats into margin.';
COMMENT ON COLUMN sale.net_proceeds IS 'Cash received: gross + shipping_charged - all fees - shipping_paid - supplies.';

-- ---------------------------------------------------------------------------
-- 4. ALLOCATION  --  spread a box's cost across its pulls by market value
-- ---------------------------------------------------------------------------
-- Call after scanning a box's contents in (with market_value_at_open set):
--     SELECT allocate_box_cost(<acquisition_id>);
-- Weighted method: each item's basis = allocatable_cost * (its value / total value).
-- Multi-day rips: if packs_opened < packs_total, only that fraction of the box
-- cost is spread over the cards opened so far; basis re-settles as you rip more,
-- and reaches the full box cost once packs_opened = packs_total.
-- Falls back to an even split if no market values are recorded yet.
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

    -- Prorate the cost by how much of the box has actually been opened.
    IF v_packs_total IS NOT NULL AND v_packs_open IS NOT NULL AND v_packs_total > 0 THEN
        v_allocatable := v_total_cost * LEAST(v_packs_open, v_packs_total)::numeric / v_packs_total;
    ELSE
        v_allocatable := v_total_cost;   -- single packs / unknown -> allocate the whole cost
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

COMMENT ON FUNCTION allocate_box_cost(bigint)
    IS 'Distribute an acquisition''s cost across its items, weighted by market_value_at_open and prorated by packs_opened/packs_total (even split if no values set).';

-- ---------------------------------------------------------------------------
-- 5. VIEWS  --  "the numbers"
-- ---------------------------------------------------------------------------

-- Per-item ledger: basis, sale, realized profit, holding period.
CREATE VIEW v_item_ledger AS
SELECT
    i.item_id,
    a.acquisition_id,
    i.name,
    i.set_code,
    i.status,
    i.condition,
    i.grader,
    i.grade,
    (i.cost_basis + i.grading_total)                      AS total_basis,
    i.market_value,
    s.sale_date,
    s.net_proceeds,
    CASE WHEN s.sale_id IS NOT NULL
         THEN s.net_proceeds - (i.cost_basis + i.grading_total) END AS realized_profit,
    CASE WHEN s.sale_id IS NOT NULL
         THEN (s.sale_date - a.purchase_date) END         AS holding_days,
    a.purchase_date,
    a.source,
    s.channel             AS sold_via
FROM item i
JOIN acquisition a ON a.acquisition_id = i.acquisition_id
LEFT JOIN sale  s  ON s.item_id        = i.item_id;

-- Per-box (acquisition) profit & loss, plus price-per-pack.
CREATE VIEW v_box_pl AS
SELECT
    a.acquisition_id,
    a.purchase_date,
    a.description,
    a.game,
    a.total_cost,
    COALESCE(SUM(i.grading_total), 0)                                 AS grading_spend,
    a.total_cost + COALESCE(SUM(i.grading_total), 0)                  AS total_invested,
    a.packs_total,
    ROUND(a.total_cost / NULLIF(a.packs_total, 0), 2)                 AS cost_per_pack,
    COUNT(i.item_id)                                                  AS items,
    COALESCE(SUM(i.market_value_at_open), 0)                          AS ev_at_open,
    COALESCE(SUM(s.net_proceeds), 0)                                  AS realized_net,
    COALESCE(SUM(i.market_value) FILTER
        (WHERE i.status IN ('inventory','listed','keep','grading')), 0) AS unsold_value,
    COALESCE(SUM(s.net_proceeds), 0)
      + COALESCE(SUM(i.market_value) FILTER
        (WHERE i.status IN ('inventory','listed','keep','grading')), 0) AS recovered_value,
    -- recovered minus everything invested (box cost + grading). The honest bottom line.
    ROUND(
        COALESCE(SUM(s.net_proceeds), 0)
        + COALESCE(SUM(i.market_value) FILTER
            (WHERE i.status IN ('inventory','listed','keep','grading')), 0)
        - a.total_cost - COALESCE(SUM(i.grading_total), 0)
    , 2)                                                              AS net_result,
    ROUND(100.0 * (
        COALESCE(SUM(s.net_proceeds), 0)
        + COALESCE(SUM(i.market_value) FILTER
            (WHERE i.status IN ('inventory','listed','keep','grading')), 0)
        - a.total_cost - COALESCE(SUM(i.grading_total), 0)
      ) / NULLIF(a.total_cost + COALESCE(SUM(i.grading_total), 0), 0), 1) AS roi_pct
FROM acquisition a
LEFT JOIN item i ON i.acquisition_id = a.acquisition_id
LEFT JOIN sale s ON s.item_id        = i.item_id
GROUP BY a.acquisition_id;

-- Overall portfolio: realized vs unrealized, all-time.
CREATE VIEW v_portfolio AS
SELECT
    (SELECT COALESCE(SUM(total_cost), 0) FROM acquisition)            AS total_invested,
    (SELECT COALESCE(SUM(net_proceeds), 0) FROM sale)                 AS total_realized_net,
    (SELECT COALESCE(SUM(s.net_proceeds - (i.cost_basis + i.grading_total)), 0)
       FROM sale s JOIN item i ON i.item_id = s.item_id)              AS realized_profit,
    (SELECT COALESCE(SUM(market_value), 0) FROM item
       WHERE status IN ('inventory','listed','keep','grading'))       AS unsold_market_value,
    (SELECT COALESCE(SUM(market_value - (cost_basis + grading_total)), 0)
       FROM item WHERE status IN ('inventory','listed','keep','grading')
         AND market_value IS NOT NULL)                                AS unrealized_profit;

-- Did grading pay? One row per graded item that has sold.
CREATE VIEW v_grading_scorecard AS
SELECT
    i.item_id,
    i.name,
    i.grader,
    i.grade,
    i.cost_basis                          AS card_basis,
    i.grading_total                       AS grading_spend,
    (i.cost_basis + i.grading_total)      AS total_basis,
    s.net_proceeds,
    s.net_proceeds - (i.cost_basis + i.grading_total) AS profit_after_grading
FROM item i
JOIN sale s ON s.item_id = i.item_id
WHERE i.grader IS NOT NULL;

-- Cards to grade or at least look at, in two tiers (grade takes precedence):
--   grade  = slab-worthy: user-flagged OR (NM AND raw value >= 25)
--   review = box outlier: raw value >= 3x the acquisition's median value (floor 0.50)
-- Only ungraded, still-owned cards. est_upside is NULL until a slab estimate is set.
-- Constants 25 / 3 / 0.50 / 30 are mirrored in routes/ledger.py — keep in sync if tuned.
CREATE VIEW v_grade_candidates AS
WITH box AS (
    SELECT acquisition_id,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY market_value) AS median_value
    FROM item
    WHERE market_value IS NOT NULL
    GROUP BY acquisition_id
)
SELECT
    i.item_id,
    i.acquisition_id,
    i.name,
    i.set_code,
    i.condition,
    i.market_value,
    i.graded_value_est,
    i.grade_candidate,
    (i.cost_basis + i.grading_total)              AS total_basis,
    (i.graded_value_est - i.market_value - 30)    AS est_upside,
    b.median_value,
    CASE
        WHEN i.grade_candidate
             OR (i.condition = 'NM' AND i.market_value >= 25)          THEN 'grade'
        WHEN i.market_value >= 0.50 AND b.median_value > 0
             AND i.market_value >= 3 * b.median_value                  THEN 'review'
    END                                           AS tier
FROM item i
LEFT JOIN box b ON b.acquisition_id = i.acquisition_id
WHERE i.grader IS NULL
  AND i.status IN ('inventory','keep')
  AND ( i.grade_candidate
        OR (i.condition = 'NM' AND i.market_value >= 25)
        OR (i.market_value >= 0.50 AND b.median_value > 0
            AND i.market_value >= 3 * b.median_value) );

COMMIT;
