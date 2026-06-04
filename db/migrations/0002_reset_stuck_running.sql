-- 0002_reset_stuck_running.sql
--
-- One-shot recovery: revert any term_requests rows stuck in 'running'
-- back to 'pending' so a future miner can pick them up.
--
-- Apply when a miner pod was killed mid-run (and didn't get to mark its
-- request done/failed) — its row would otherwise stay 'running' forever
-- and the term would never get re-mined.
--
-- Apply with:
--   kubectl apply -f k8s/apply-migration-job.yaml   (after editing the
--   command to point at this file), OR
--   python scripts/apply_migration.py db/migrations/0002_reset_stuck_running.sql

UPDATE term_requests
SET status = 'pending',
    processed_at = NULL,
    error_message = NULL
WHERE status = 'running';
