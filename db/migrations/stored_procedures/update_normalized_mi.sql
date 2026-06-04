-- update_normalized_mi.sql
--
-- ALTERNATIVE IMPLEMENTATION (not used in production at paper submission).
--
-- This procedure provides a pure in-database NPMI computation as an
-- alternative to the application-layer implementation in
-- services/metrics.py::compute_npmi(). The production system as described
-- in the paper uses the application-layer approach; this stored procedure
-- is included so future deployments can shift NPMI computation into the
-- database if desired.
--
-- To use this in-database path, also add a `normalized_mi` column to
-- term_cooccurrence (DOUBLE PRECISION) and add `CALL update_normalized_mi();`
-- to the orchestrator update_all_statistics().
--
-- Full-table NPMI (normalized PMI; Bouma 2009) recompute. Idempotent
-- (CREATE OR REPLACE). Populates a `normalized_mi` column on
-- term_cooccurrence from the raw `prob_w1w2` and the marginal
-- probabilities on `term_counts`.
--
-- Formula:
--     NPMI(w1, w2) = ln(p(w1, w2) / (p(w1) * p(w2))) / -ln(p(w1, w2))
--
-- Note: the conversion factor ln(2) cancels between numerator and
-- denominator, so NPMI can be expressed in natural log (LN) without
-- losing the base-2 interpretation. The result is bounded to
-- approximately [-1, +1].
--
-- Behaviour on edge cases:
--   * prob_w1w2 = 0 (terms never co-occur) → NPMI is undefined; stored as NULL
--   * prob_w1w2 = 1 (terms always co-occur, denominator → 0) → NPMI = +1
--   * any marginal probability = 0 → NPMI is undefined; stored as NULL
--
-- Apply with:
--   psql -d geonlp_db -f db/migrations/stored_procedures/update_normalized_mi.sql

CREATE OR REPLACE PROCEDURE public.update_normalized_mi()
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    UPDATE term_cooccurrence wc
    SET normalized_mi = CASE
        WHEN wc.prob_w1w2 IS NULL
          OR wc1.probability IS NULL
          OR wc2.probability IS NULL
          OR wc.prob_w1w2 <= 0
          OR wc1.probability <= 0
          OR wc2.probability <= 0 THEN NULL
        WHEN wc.prob_w1w2 >= 1 THEN 1.0   -- always co-occur → perfect association
        ELSE
            LN(wc.prob_w1w2 / (wc1.probability * wc2.probability))
            / (-LN(wc.prob_w1w2))
    END
    FROM term_counts wc1, term_counts wc2
    WHERE wc.word_1 = wc1.word
      AND wc.word_2 = wc2.word;

    RAISE NOTICE 'Normalized Mutual Information (NPMI) updated successfully.';
END;
$procedure$
;
