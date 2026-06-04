-- 9999_update_probabilities.sql
--
-- Authoritative source for the full-table prob_notw1w2 recompute.
-- Captured from the live NAS Postgres on 2026-04-28. Idempotent.

CREATE OR REPLACE PROCEDURE public.update_probabilities()
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    UPDATE term_cooccurrence wc
    SET prob_notw1w2 =
        CASE
            WHEN wc1.probability IS NULL OR wc2.probability IS NULL OR wc.prob_w1w2 IS NULL THEN NULL
            ELSE 1 - wc1.probability - wc2.probability - wc.prob_w1w2
        END
    FROM term_counts wc1, term_counts wc2
    WHERE wc.word_1 = wc1.word
      AND wc.word_2 = wc2.word;

    RAISE NOTICE 'Term cooccurrence probabilities updated successfully.';
END;
$procedure$
;
