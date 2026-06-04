-- 0005_term_class.sql
--
-- Adds a `term_class` column to `term_requests` so the mining workers
-- can be segregated into pools by workload size.
--
-- Background
-- ----------
-- Up to this migration, every miner pod claimed from the same FIFO
-- queue. High-frequency terms (5M+ unique partner tokens) hog a pod
-- slot for many hours and intermittently OOM, while small terms wait
-- behind them. Pool segregation routes a term to the appropriate
-- worker pool based on its xDD snippet count at classification time.
--
-- Classes
-- -------
--   small      : hits <       100,000     fast (<30 min), 1 GiB pod is plenty
--   medium     : hits <     1,000,000     moderate, 1 GiB pod OK
--   large      : hits <    10,000,000     slow, requires 4 GiB pod + pruning
--   oversized  : hits >=  10,000,000      auto-fail (or, later, sharded miner)
--
-- These thresholds live in services/mining_config.py and may be re-tuned;
-- the column constraint only enforces the *names*, not the boundaries.
--
-- Backfill / migration story
-- --------------------------
-- The column is nullable. Rows with term_class IS NULL are claimable
-- by ANY pool (defensive default during rollout). A separate
-- `classify_pending_terms.py` CronJob runs every 30 min and fills in
-- the class for unclassified pending rows. Manual backfill of the
-- existing queue can be done by running the classifier in foreground:
--   python scripts/classify_pending_terms.py --batch-size 500 --once
--
-- The existing pre-flight `SNAPSHOT_MAX_SNIPPETS_PER_TERM` check in
-- process_term() is retained as defense in depth.
--
-- Apply via:
--   sed -i 's|0001_term_requests_status.sql|0005_term_class.sql|' k8s/apply-migration-job.yaml
--   kubectl delete job geonlp-apply-migration --ignore-not-found
--   kubectl apply -f k8s/apply-migration-job.yaml
--   kubectl wait --for=condition=complete --timeout=60s job/geonlp-apply-migration
--   kubectl logs job/geonlp-apply-migration
--   sed -i 's|0005_term_class.sql|0001_term_requests_status.sql|' k8s/apply-migration-job.yaml
--
-- Idempotent — safe to re-run.

ALTER TABLE term_requests
    ADD COLUMN IF NOT EXISTS term_class TEXT NULL,
    ADD COLUMN IF NOT EXISTS hits_at_classify BIGINT NULL,
    ADD COLUMN IF NOT EXISTS classified_at TIMESTAMP NULL;

-- Enforce the allowed class names. NULL is allowed and means
-- "unclassified — pool routing falls back to claim-by-any."
ALTER TABLE term_requests
    DROP CONSTRAINT IF EXISTS term_requests_term_class_chk;
ALTER TABLE term_requests
    ADD CONSTRAINT term_requests_term_class_chk
    CHECK (term_class IS NULL OR term_class IN ('small','medium','large','oversized'));

-- Partial index on (term_class, status, requested_at) for pending rows.
-- Workers query: WHERE status='pending' AND term_class IN (...) ORDER BY requested_at.
-- A partial index keyed to status='pending' keeps the index tiny — the
-- pending set is at most a few thousand rows even on a fully-loaded
-- queue, vs. tens of thousands of done/failed rows we'd otherwise pay
-- index-maintenance for.
CREATE INDEX IF NOT EXISTS term_requests_class_pending_idx
    ON term_requests (term_class, requested_at)
    WHERE status = 'pending';

-- Index supporting the classifier's discovery query:
-- WHERE status='pending' AND term_class IS NULL.
-- Partial again — only the unclassified-pending subset matters.
CREATE INDEX IF NOT EXISTS term_requests_unclassified_pending_idx
    ON term_requests (requested_at)
    WHERE status = 'pending' AND term_class IS NULL;
