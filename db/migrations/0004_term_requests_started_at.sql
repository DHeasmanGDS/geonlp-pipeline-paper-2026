-- 0004_term_requests_started_at.sql
--
-- Adds the `started_at` timestamp the janitor uses to detect zombie
-- 'running' rows (pods that died mid-mining without marking their
-- request done/failed — typically OOM-kill, manual delete, or
-- eviction).
--
-- Also one-shot resets any rows currently stuck in 'running' that
-- predate this column (no started_at value to compare against, so
-- they'd otherwise be invisible to the time-based janitor).
--
-- Idempotent — safe to re-run.
--
-- Apply via:
--   sed -i 's|0001_term_requests_status.sql|0004_term_requests_started_at.sql|' k8s/apply-migration-job.yaml
--   kubectl delete job geonlp-apply-migration --ignore-not-found
--   kubectl apply -f k8s/apply-migration-job.yaml
--   kubectl wait --for=condition=complete --timeout=60s job/geonlp-apply-migration
--   kubectl logs job/geonlp-apply-migration
--   sed -i 's|0004_term_requests_started_at.sql|0001_term_requests_status.sql|' k8s/apply-migration-job.yaml

ALTER TABLE term_requests
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMP NULL;

-- Index supports the janitor's "find zombies" query: WHERE status='running'
-- AND started_at < NOW() - INTERVAL '...'. Partial because only
-- 'running' rows are ever scanned.
CREATE INDEX IF NOT EXISTS term_requests_running_started_idx
    ON term_requests (started_at)
    WHERE status = 'running';

-- One-shot recovery for any rows currently stuck in 'running' that
-- predate the column. They have no started_at to compare against, so
-- the janitor can't see them. Reset to pending so a future miner
-- picks them up cleanly.
UPDATE term_requests
SET status = 'pending',
    processed_at = NULL,
    error_message = NULL
WHERE status = 'running'
  AND started_at IS NULL;
