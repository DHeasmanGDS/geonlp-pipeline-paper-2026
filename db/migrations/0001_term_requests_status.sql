-- 0001_term_requests_status.sql
--
-- Adds status tracking to term_requests so the mining CronJob can:
--   1. Pick up pending requests in FIFO order
--   2. Lock a row while it's being processed (FOR UPDATE SKIP LOCKED)
--   3. Record success/failure with diagnostic detail
--
-- Apply once on the NAS:
--   docker exec -i geonlp-postgres psql -U geonlp -d geonlp_db < 0001_term_requests_status.sql
--
-- Idempotent: safe to re-run.

ALTER TABLE term_requests
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS error_message TEXT NULL;

-- Allowed values: pending | running | done | failed
ALTER TABLE term_requests
    DROP CONSTRAINT IF EXISTS term_requests_status_chk;
ALTER TABLE term_requests
    ADD CONSTRAINT term_requests_status_chk
    CHECK (status IN ('pending', 'running', 'done', 'failed'));

-- Speeds up the worker's "next pending" query.
CREATE INDEX IF NOT EXISTS term_requests_status_idx
    ON term_requests (status, requested_at);
