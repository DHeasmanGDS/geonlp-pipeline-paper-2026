-- schema.sql
--
-- Consolidated PostgreSQL schema for fresh installs.
-- Reflects the cumulative state of the production database after all
-- migrations under db/migrations/ have been applied, as captured from
-- the live cluster at paper submission.
--
-- For historical accuracy (migration-by-migration), apply the numbered
-- migration files in db/migrations/ in order instead.
--
-- Tested on PostgreSQL 15.17. Requires no extensions.
--
-- Apply with a single command (includes all stored procedures via \ir):
--   psql -d geonlp_db -f db/schema.sql

-- ============================================================================
-- processed_terms
-- ============================================================================
-- Audit log of which terms have completed mining. Existence of a row here is
-- the canonical "this term has been mined" signal (used for idempotency).
-- Single column by design — audit timestamps live in term_requests.

CREATE TABLE IF NOT EXISTS processed_terms (
    term TEXT PRIMARY KEY
);

-- ============================================================================
-- term_counts
-- ============================================================================
-- Per-term frequency statistics. One row per unique word observed across
-- the corpus. The `count` column for a seed-term row equals the number of
-- snippets returned for that seed mine; for a partner-term row, it equals
-- the number of times that word appeared as a token across all snippets
-- of the mining seed terms that touched it.
--
-- Snapshot provenance fields (mining_max_acquired, mining_total_docs,
-- mining_tokens_per_doc) record the xDD snapshot state at compute time so
-- cohorts from different snapshots can be distinguished and probability
-- calculations remain consistent within a cohort.

CREATE TABLE IF NOT EXISTS term_counts (
    word                    TEXT PRIMARY KEY,
    count                   INTEGER,
    probability             DOUBLE PRECISION,
    entropy                 DOUBLE PRECISION,
    -- Per-row snapshot provenance
    mining_max_acquired     DATE,
    mining_total_docs       BIGINT,
    mining_tokens_per_doc   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_term_counts_snapshot
    ON term_counts (mining_max_acquired);

-- ============================================================================
-- term_cooccurrence
-- ============================================================================
-- Pairwise co-occurrence counts and information-theoretic metrics.
-- Hash-partitioned across 32 partitions on word_1 for query performance.
--
-- Note on column semantics:
--   mutual_information = prob_w1w2 * LOG(prob_w1w2 / (p1 * p2)) / LN(2)
-- This is the per-pair contribution to total mutual information (weighted
-- by joint probability) in mixed units. True bit-valued PMI and NPMI are
-- computed at query time by services.metrics.compute_pmi_bits() and
-- services.metrics.compute_npmi() — see that module's docstring for the
-- conversion arithmetic and rationale.

CREATE TABLE IF NOT EXISTS term_cooccurrence (
    word_1              TEXT NOT NULL,
    word_2              TEXT NOT NULL,
    count               INTEGER NOT NULL,
    prob_w1w2           DOUBLE PRECISION,
    mutual_information  DOUBLE PRECISION,
    entropy_w1w2        DOUBLE PRECISION,
    prob_notw1w2        DOUBLE PRECISION,
    entropy_notw1w2     DOUBLE PRECISION,
    mining_max_acquired DATE,
    PRIMARY KEY (word_1, word_2),
    CONSTRAINT fk_word_1_processed_terms
        FOREIGN KEY (word_1) REFERENCES processed_terms (term)
        ON DELETE CASCADE,
    CONSTRAINT fk_word_1_term_counts
        FOREIGN KEY (word_1) REFERENCES term_counts (word)
        ON DELETE CASCADE
) PARTITION BY HASH (word_1);

-- Create 32 hash partitions.
DO $$
DECLARE
    i INTEGER;
BEGIN
    FOR i IN 0..31 LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS term_cooccurrence_p%s
             PARTITION OF term_cooccurrence
             FOR VALUES WITH (MODULUS 32, REMAINDER %s)',
            i, i
        );
    END LOOP;
END $$;

-- ============================================================================
-- term_requests
-- ============================================================================
-- Operational queue of terms awaiting mining (or actively being mined).
-- Separate from term_counts because this is a mutable work queue with
-- state transitions; term_counts is append-only canonical data.

CREATE TABLE IF NOT EXISTS term_requests (
    id              SERIAL PRIMARY KEY,
    term            VARCHAR(255) NOT NULL UNIQUE,
    status          VARCHAR(50) DEFAULT 'pending',
    requested_at    TIMESTAMP DEFAULT NOW(),
    started_at      TIMESTAMP NULL,
    processed_at    TIMESTAMP NULL,
    error_message   TEXT NULL,
    notes           TEXT NULL,
    request_count   INTEGER DEFAULT 1,
    -- Phase 1 pool segregation
    term_class          TEXT NULL,
    hits_at_classify    BIGINT NULL,
    classified_at       TIMESTAMP NULL,
    CONSTRAINT term_requests_status_chk
        CHECK (status IN ('pending', 'running', 'done', 'failed')),
    CONSTRAINT term_requests_term_class_chk
        CHECK (term_class IS NULL OR term_class IN ('small','medium','large','oversized'))
);

-- Indexes supporting the worker and classifier query patterns.
CREATE INDEX IF NOT EXISTS term_requests_status_idx
    ON term_requests (status, requested_at);

CREATE INDEX IF NOT EXISTS term_requests_running_started_idx
    ON term_requests (started_at)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS term_requests_class_pending_idx
    ON term_requests (term_class, requested_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS term_requests_unclassified_pending_idx
    ON term_requests (requested_at)
    WHERE status = 'pending' AND term_class IS NULL;

-- ============================================================================
-- Stored procedures
-- ============================================================================
-- These compute the derived columns (probability, mutual_information,
-- joint entropy, Shannon entropy) in-database from raw counts. NPMI and
-- true bit-valued PMI are derived from these stored values by the
-- application layer at query time (see services/metrics.py).
--
-- \ir is psql's "include relative" — it loads each file relative to the
-- directory containing schema.sql, so the single command
--   psql -d geonlp_db -f db/schema.sql
-- applies the entire schema and all procedures in one pass.

\ir migrations/stored_procedures/update_probabilities.sql
\ir migrations/stored_procedures/update_mutual_information.sql
\ir migrations/stored_procedures/update_word_entropy.sql
\ir migrations/stored_procedures/update_word_cooccurrence_entropy.sql
\ir migrations/stored_procedures/update_all_statistics.sql
\ir migrations/stored_procedures/update_all_statistics_for_term.sql

-- Note: update_normalized_mi.sql is intentionally NOT included here. It is
-- an alternative implementation provided for future deployments that wish
-- to compute NPMI in-database instead of in the application layer; see
-- the file header for migration instructions if you want to switch to that
-- approach.
