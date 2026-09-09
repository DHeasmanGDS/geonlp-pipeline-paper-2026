-- 9999_update_word_cooccurrence_entropy.sql
--
-- Authoritative source for the full-table entropy recompute on
-- term_cooccurrence (both entropy_w1w2 and entropy_notw1w2 columns).
-- Captured from the live NAS Postgres on 2026-04-28. Idempotent.

CREATE OR REPLACE PROCEDURE public.update_word_cooccurrence_entropy()
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    UPDATE term_cooccurrence
    SET entropy_w1w2 = CASE
        WHEN prob_w1w2 > 0 THEN -prob_w1w2 * (LN(prob_w1w2) / LN(2))
        ELSE NULL
    END;

    UPDATE term_cooccurrence
    SET entropy_notw1w2 = CASE
        WHEN prob_notw1w2 > 0 THEN -prob_notw1w2 * (LN(prob_notw1w2) / LN(2))
        ELSE NULL
    END;

    RAISE NOTICE 'Entropy updated successfully for term_cooccurrence table.';
END;
$procedure$
;
