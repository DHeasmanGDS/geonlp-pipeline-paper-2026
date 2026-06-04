-- schema.sql
--
-- Consolidated PostgreSQL schema for fresh installs.
-- This file reflects the cumulative state after all migrations under
-- db/migrations/ have been applied. Use this for a clean deployment.
--
-- For historical accuracy (migration-by-migration), apply the numbered
-- migration files in db/migrations/ in order instead.
--
-- Tested on PostgreSQL 15.17. Requires no extensions.
--
-- Apply with:
--   psql -d geonlp_db -f db/schema.sql
--   psql -d geonlp_db -f db/migrations/stored_procedures/update_probabilities.sql
--   psql -d geonlp_db -f db/migrations/stored_procedures/update_mutual_information.sql
--   psql -d geonlp_db -f db/migrations/stored_procedures/update_word_entropy.sql
--   psql -d geonlp_db -f db/migrations/stored_procedures/update_word_cooccurrence_entropy.sql
--   psql -d geonlp_db -f db/migrations/stored_procedures/update_all_statistics.sql
--   psql -d geonlp_db -f db/migrations/stored_procedures/update_all_statistics_for_term.sql

-- ============================================================================
-- processed_terms
-- ============================================================================
-- Audit log of which terms have completed mining. Existence of a row here is
-- the canonical "this term has been mined" signal (used for idempotency).

CREATE TABLE IF NOT EXISTS processed_terms (
    term        TEXT PRIMARY KEY,
    processed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- term_counts
-- ============================================================================
-- Per-term frequency statistics. One row per unique word observed across
-- the corpus. The `count` column for a seed-term row equals the number of
-- snippets returned for that seed mine; for a partner-term row, it equals
-- the number of times that word appeared as a token across all snippets
-- of the mining seed term that touched it.
--
-- Snapshot provenance fields (mining_max_acquired, mining_total_docs,
-- mining_tokens_per_doc) record the xDD snapshot state at compute time so
-- cohorts from different snapshots can be distinguished and probability
-- calculations remain consistent within a cohort.

CREATE TABLE IF NOT EXISTS term_counts (
    word                    TEXT PRIMARY KEY,
    count                   BIGINT NOT NULL,
    probability             DOUBLE PRECISION,
    entropy                 DOUBLE PRECISION,
    -- Per-row snapshot provenance
    mining_max_acquired     DATE,
    mining_total_docs       BIGINT,
    mining_tokens_per_doc   INTEGER
);

-- ============================================================================
-- term_cooccurrence
-- ============================================================================
-- Pairwise co-occurrence counts and information-theoretic metrics.
-- Hash-partitioned across 32 partitions on word_1 for query performance.

CREATE TABLE IF NOT EXISTS term_cooccurrence (
    word_1                  TEXT NOT NULL,
    word_2                  TEXT NOT NULL,
    count                   BIGINT NOT NULL,
    prob_w1w2               DOUBLE PRECISION,
    mutual_information      DOUBLE PRECISION,
    normalized_mi           DOUBLE PRECISION,   -- NPMI (Bouma 2009)
    entropy_w1w2            DOUBLE PRECISION,
    mining_max_acquired     DATE,
    mining_total_docs       BIGINT,
    mining_tokens_per_doc   INTEGER,
    PRIMARY KEY (word_1, word_2),
    CONSTRAINT fk_word_1_processed_terms
        FOREIGN KEY (word_1) REFERENCES processed_terms (term)
        ON DELETE CASCADE,
    CONSTRAINT fk_word_1_term_counts
        FOREIGN KEY (word_1) REFERENCES term_counts (word),
    CONSTRAINT fk_word_2_term_counts
        FOREIGN KEY (word_2) REFERENCES term_counts (word)
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
    status          TEXT NOT NULL DEFAULT 'pending',
    requested_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMP NULL,
    processed_at    TIMESTAMP NULL,
    error_message   TEXT NULL,
    request_count   INTEGER NOT NULL DEFAULT 1,
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
-- Apply stored procedures
-- ============================================================================
-- These compute the derived columns (probability, mutual_information, NPMI,
-- entropy) in-database from raw counts. Defined in:
--   db/migrations/stored_procedures/*.sql
-- Apply each in sequence after this schema.
