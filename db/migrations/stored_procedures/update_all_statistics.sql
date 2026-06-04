-- 9999_update_all_statistics.sql
--
-- Authoritative source for the orchestration wrapper that recomputes
-- mutual information / entropy across term_cooccurrence. Captured from
-- the live NAS Postgres on 2026-04-28 via:
--
--   SELECT pg_get_functiondef(p.oid)
--   FROM pg_proc p
--   WHERE p.proname='update_all_statistics';
--
-- This wrapper is just the orchestrator — the actual math lives in the
-- four sub-procedures it calls (see the sibling files
-- 9999_update_*.sql once they're captured). Total runtime is dominated
-- by `update_mutual_information()`; the full chain currently takes
-- ~3 hours on a 9GB term_cooccurrence table.
--
-- Apply with:
--   python scripts/apply_migration.py db/migrations/9999_update_all_statistics.sql
--   # OR via the kubectl Job manifest after editing it to point here.
--
-- This file uses CREATE OR REPLACE so re-applying is safe and idempotent.

CREATE OR REPLACE PROCEDURE public.update_all_statistics()
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    -- Step 1: Update mutual information
    CALL update_mutual_information();
    RAISE NOTICE 'Step 1: Mutual information updated.';

    -- Step 2: Update probabilities
    CALL update_probabilities();
    RAISE NOTICE 'Step 2: Probabilities updated.';

    -- Step 3: Update word cooccurrence entropy
    CALL update_word_cooccurrence_entropy();
    RAISE NOTICE 'Step 3: Word cooccurrence entropy updated.';

    -- Step 4: Update word entropy
    CALL update_word_entropy();
    RAISE NOTICE 'Step 4: Word entropy updated.';

    -- Log completion
    RAISE NOTICE 'All statistics updated successfully.';
END;
$procedure$
;
