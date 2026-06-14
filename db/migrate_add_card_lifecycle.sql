-- =============================================================================
-- Migration: card lifecycle (grading triage) — ADDITIVE, safe on live data
-- =============================================================================
-- Adds two nullable/defaulted columns to card_ledger.item and the
-- v_grade_candidates view. Touches no existing row's data; existing row COUNT
-- and values are unchanged. Idempotent (safe to re-run).
--
-- Run once:  psql -d media -f db/migrate_add_card_lifecycle.sql
-- =============================================================================

BEGIN;

SET search_path TO card_ledger, public;

ALTER TABLE item ADD COLUMN IF NOT EXISTS
    grade_candidate  boolean NOT NULL DEFAULT false;      -- triage: "this should be graded"
ALTER TABLE item ADD COLUMN IF NOT EXISTS
    graded_value_est numeric(12,2);                       -- optional est. slab value -> upside

-- Rule-based + user-flagged grading candidates (see card_ledger_schema.sql).
DROP VIEW IF EXISTS v_grade_candidates;
CREATE VIEW v_grade_candidates AS
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
    (i.graded_value_est - i.market_value - 30)    AS est_upside
FROM item i
WHERE i.grader IS NULL
  AND i.status IN ('inventory','keep')
  AND ( i.grade_candidate
        OR (i.condition = 'NM' AND i.market_value >= 25) );

COMMIT;
