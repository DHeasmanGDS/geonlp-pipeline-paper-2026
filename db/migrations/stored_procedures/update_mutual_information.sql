-- 9999_update_mutual_information.sql
--
-- Authoritative source for the full-table MI recompute. Captured from
-- the live NAS Postgres on 2026-04-28. Idempotent (CREATE OR REPLACE).
--
-- Scans every row in term_cooccurrence joined twice to term_counts.
-- This is the slowest of the four sub-procs and dominates the ~3h
-- runtime of update_all_statistics(). Replaced for the per-term path
-- by update_mutual_information_for_term() in 9999_update_all_statistics_for_term.sql.

CREATE OR REPLACE PROCEDURE public.update_mutual_information()
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    UPDATE term_cooccurrence wc
    SET mutual_information = CASE
        WHEN wc.prob_w1w2 > 0 AND wc1.probability > 0 AND wc2.probability > 0 THEN
            wc.prob_w1w2 * LOG(wc.prob_w1w2 / (wc1.probability * wc2.probability)) / LN(2)
        ELSE NULL
    END
    FROM term_counts wc1, term_counts wc2
    WHERE wc.word_1 = wc1.word
      AND wc.word_2 = wc2.word;

    RAISE NOTICE 'Mutual Information updated successfully.';
END;
$procedure$
;
