-- 0003_reset_fk_failures.sql
--
-- One-shot recovery: term_requests rows that failed due to the
-- "fk_word_1_processed_terms" foreign-key violation in the worker's
-- original insert ordering bug. Reset them to 'pending' so the patched
-- worker can retry them.
--
-- Does NOT touch failures with other causes (e.g. legitimate "xDD
-- returned no snippets for X" failures) — those should remain failed.
--
-- Apply with the kubectl Job (edit k8s/apply-migration-job.yaml to
-- point at this file).

UPDATE term_requests
SET status = 'pending',
    processed_at = NULL,
    error_message = NULL
WHERE status = 'failed'
  AND error_message LIKE '%ForeignKeyViolation%';
