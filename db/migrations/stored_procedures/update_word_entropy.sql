-- 9999_update_word_entropy.sql
--
-- Authoritative source for the full-table entropy recompute on
-- term_counts. Captured from the live NAS Postgres on 2026-04-28.
-- Idempotent.

CREATE OR REPLACE PROCEDURE public.update_word_entropy()
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    UPDATE term_counts
    SET entropy = CASE
        WHEN probability > 0 THEN -probability * (LN(probability) / LN(2))
        ELSE NULL
    END;

    RAISE NOTICE 'Entropy updated successfully.';
END;
$procedure$
;
