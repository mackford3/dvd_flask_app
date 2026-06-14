-- =============================================================================
-- Migration: multi-game support + grading Review tier  (additive + backfill)
-- =============================================================================
-- 1. Widen acquisition.game to allow 'pokemon' and 'mixed'.
-- 2. Add per-card item.game (nullable; backfilled from the parent acquisition).
-- 3. Rewrite v_grade_candidates with two tiers (grade / review).
--
-- The only write to existing rows is the derivable backfill item.game := acquisition.game
-- (existing cards are all Weiss -> 'weiss'). Row counts are unchanged. Idempotent.
-- Run once:  psql -d media -f db/migrate_multigame_and_review.sql
-- =============================================================================

BEGIN;

SET search_path TO card_ledger, public;

-- 1. acquisition.game CHECK -> add 'pokemon','mixed'
ALTER TABLE acquisition DROP CONSTRAINT IF EXISTS acquisition_game_check;
ALTER TABLE acquisition ADD  CONSTRAINT acquisition_game_check
    CHECK (game IN ('mtg','weiss','pokemon','other','mixed'));

-- 2. per-card game (nullable; CHECK excludes 'mixed' — that's an acquisition-level label)
ALTER TABLE item ADD COLUMN IF NOT EXISTS
    game text CHECK (game IS NULL OR game IN ('mtg','weiss','pokemon','other'));

UPDATE item i
SET game = a.game
FROM acquisition a
WHERE i.acquisition_id = a.acquisition_id
  AND i.game IS NULL
  AND a.game IN ('mtg','weiss','pokemon','other');

-- 3. two-tier grading candidates (grade / review). Constants mirror routes/ledger.py.
DROP VIEW IF EXISTS v_grade_candidates;
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
