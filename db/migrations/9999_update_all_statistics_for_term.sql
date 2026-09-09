-- 9999_update_all_statistics_for_term.sql
--
-- Per-term incremental versions of the four statistics-update
-- procedures. Math is identical to the full-table versions in
-- 9999_update_*.sql; only the WHERE clauses change.
--
-- Why this exists: the full chain (update_all_statistics) takes ~3h
-- on a 9GB term_cooccurrence table because it UPDATEs every row four
-- times. The math is per-row local — no cross-row aggregation — so
-- the recompute can be scoped to the rows that actually changed when
-- a single term is mined. Per-term variants complete in milliseconds.
--
-- Two-direction MI / probability filter: when a term X is freshly
-- mined, three categories of rows can have stale derived columns:
--   1. Rows where word_1 = X — brand new, never had MI/entropy computed
--   2. Rows where word_2 = X — existed before X was in term_counts;
--      their MI/prob_notw1w2 was NULL because the JOIN to term_counts
--      excluded them. Now eligible.
--   3. Rows where word_2 = X had entropy_w1w2 computed at the time of
--      their mining (depends only on their own prob_w1w2, which didn't
--      change). So entropy_w1w2 only needs the word_1 = X filter.
--
-- update_word_entropy_for_term touches term_counts only for the new
-- term itself; partner terms' entropy values were already correct.
--
-- Apply once via:
--   python scripts/apply_migration.py db/migrations/9999_update_all_statistics_for_term.sql
-- (or via the kubectl Job manifest after editing).
--
-- Idempotent (CREATE OR REPLACE).

CREATE OR REPLACE PROCEDURE public.update_mutual_information_for_term(in_term TEXT)
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    -- Direction 1: rows just inserted with word_1 = in_term.
    -- Partition-pruned via word_1.
    UPDATE term_cooccurrence wc
    SET mutual_information = CASE
        WHEN wc.prob_w1w2 > 0 AND wc1.probability > 0 AND wc2.probability > 0 THEN
            wc.prob_w1w2 * LOG(wc.prob_w1w2 / (wc1.probability * wc2.probability)) / LN(2)
        ELSE NULL
    END
    FROM term_counts wc1, term_counts wc2
    WHERE wc.word_1 = wc1.word
      AND wc.word_2 = wc2.word
      AND wc.word_1 = in_term;

    -- Direction 2: rows from previously mined terms whose word_2 = in_term.
    -- Their MI was NULL because in_term wasn't in term_counts at the
    -- time those rows were mined.
    UPDATE term_cooccurrence wc
    SET mutual_information = CASE
        WHEN wc.prob_w1w2 > 0 AND wc1.probability > 0 AND wc2.probability > 0 THEN
            wc.prob_w1w2 * LOG(wc.prob_w1w2 / (wc1.probability * wc2.probability)) / LN(2)
        ELSE NULL
    END
    FROM term_counts wc1, term_counts wc2
    WHERE wc.word_1 = wc1.word
      AND wc.word_2 = wc2.word
      AND wc.word_2 = in_term;
END;
$procedure$
;


CREATE OR REPLACE PROCEDURE public.update_probabilities_for_term(in_term TEXT)
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    -- Direction 1: rows where word_1 = in_term (just-mined).
    UPDATE term_cooccurrence wc
    SET prob_notw1w2 =
        CASE
            WHEN wc1.probability IS NULL OR wc2.probability IS NULL OR wc.prob_w1w2 IS NULL THEN NULL
            ELSE 1 - wc1.probability - wc2.probability - wc.prob_w1w2
        END
    FROM term_counts wc1, term_counts wc2
    WHERE wc.word_1 = wc1.word
      AND wc.word_2 = wc2.word
      AND wc.word_1 = in_term;

    -- Direction 2: rows where word_2 = in_term (newly eligible).
    UPDATE term_cooccurrence wc
    SET prob_notw1w2 =
        CASE
            WHEN wc1.probability IS NULL OR wc2.probability IS NULL OR wc.prob_w1w2 IS NULL THEN NULL
            ELSE 1 - wc1.probability - wc2.probability - wc.prob_w1w2
        END
    FROM term_counts wc1, term_counts wc2
    WHERE wc.word_1 = wc1.word
      AND wc.word_2 = wc2.word
      AND wc.word_2 = in_term;
END;
$procedure$
;


CREATE OR REPLACE PROCEDURE public.update_word_cooccurrence_entropy_for_term(in_term TEXT)
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    -- entropy_w1w2 depends only on prob_w1w2 — only the just-mined
    -- rows (word_1 = in_term) have new prob_w1w2 values.
    UPDATE term_cooccurrence
    SET entropy_w1w2 = CASE
        WHEN prob_w1w2 > 0 THEN -prob_w1w2 * (LN(prob_w1w2) / LN(2))
        ELSE NULL
    END
    WHERE word_1 = in_term;

    -- entropy_notw1w2 depends on prob_notw1w2, which was just refreshed
    -- in BOTH directions by update_probabilities_for_term. Keep entropy
    -- in lock-step.
    UPDATE term_cooccurrence
    SET entropy_notw1w2 = CASE
        WHEN prob_notw1w2 > 0 THEN -prob_notw1w2 * (LN(prob_notw1w2) / LN(2))
        ELSE NULL
    END
    WHERE word_1 = in_term OR word_2 = in_term;
END;
$procedure$
;


CREATE OR REPLACE PROCEDURE public.update_word_entropy_for_term(in_term TEXT)
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    UPDATE term_counts
    SET entropy = CASE
        WHEN probability > 0 THEN -probability * (LN(probability) / LN(2))
        ELSE NULL
    END
    WHERE word = in_term;
END;
$procedure$
;


CREATE OR REPLACE PROCEDURE public.update_all_statistics_for_term(in_term TEXT)
 LANGUAGE plpgsql
AS $procedure$
BEGIN
    -- Step 1: prob_notw1w2 must run BEFORE entropy_notw1w2 since the
    -- latter consumes the former.
    CALL update_probabilities_for_term(in_term);

    -- Step 2: mutual information.
    CALL update_mutual_information_for_term(in_term);

    -- Step 3: cooccurrence entropies (both columns).
    CALL update_word_cooccurrence_entropy_for_term(in_term);

    -- Step 4: term-level entropy (just the term itself in term_counts).
    CALL update_word_entropy_for_term(in_term);
END;
$procedure$
;
