# Snapshot State

This repository is a frozen snapshot accompanying Heasman & Eglington (2026).
It captures the codebase at the time of paper submission and will NOT receive
future updates beyond corrections directly tied to the paper itself.

For the actively evolving codebase, contact the corresponding author.

## Snapshot metadata

| Field | Value |
|---|---|
| **Snapshot taken** | [FILL IN: date you publish the repo] |
| **Source commit SHA** | [FILL IN: git rev-parse HEAD from your private repo] |
| **xDD snapshot date** | 2026-05-18 |
| **Mining cutoff date** | 2026-06-04 |
| **Initial MSc-curated terms** | 1,094 |
| **Community-contributed terms** | ~3,885 |
| **Total candidate terms** | ~5,000 |
| **Mined terms at cutoff** | 2,320 |
| **Total snippets** | ~2.2 billion |
| **Total tokens (estimated)** | ~9.5 trillion |
| **PostgreSQL version used** | 15.17 (Debian 15.17-1.pgdg13+1) |
| **Python version used** | 3.11 |
| **Kubernetes version used** | k3s v1.30 (single-node) |

## What "frozen" means

- Bug fixes are accepted only if they affect a result reported in the paper.
- Cosmetic / refactoring changes are not accepted.
- New features (e.g. additional pipeline stages) are not back-ported here.
- The companion paper (Heasman and Eglington, in preparation) may reference an
  evolved version of this codebase; that version is not included in this repository.

## Migration sequence as run on the production database

The migrations in `db/migrations/` were applied in this order during the build
of the corpus reported in the paper:

```
0001_term_requests_status.sql       (initial status/queue columns)
0002_reset_stuck_running.sql        (one-shot operational fix; idempotent no-op now)
0003_reset_fk_failures.sql          (one-shot operational fix; idempotent no-op now)
0004_term_requests_started_at.sql   (zombie detection support)
0005_term_class.sql                 (pool segregation classifier)

stored_procedures/update_probabilities.sql
stored_procedures/update_mutual_information.sql
stored_procedures/update_word_entropy.sql
stored_procedures/update_word_cooccurrence_entropy.sql
stored_procedures/update_all_statistics.sql           (orchestrator)
stored_procedures/update_all_statistics_for_term.sql  (incremental)
```

For a fresh install, `db/schema.sql` consolidates all of the above into a
single script (preferred for new deployments).
