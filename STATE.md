# Snapshot State

This repository is a frozen snapshot accompanying Heasman & Eglington (2026),
submitted to *Computers & Geosciences*. It captures the codebase at the state
that produced the corpus reported in the paper and will NOT receive future
updates beyond corrections directly tied to the paper itself.

For the actively evolving codebase, contact the corresponding author.

## Snapshot metadata

| Field | Value |
|---|---|
| **Snapshot taken** | 2026-09-09 (v2.0; supersedes the 2026-06-04 v1.x pre-submission cut) |
| **Source commit SHA** | `8108f4b6e17fe7d0240d30846c74a4e3dc003b3f` (private repo, 2026-08-15 — the state that produced the submitted corpus) |
| **xDD snapshot date (`max_acquired` pin)** | 2026-05-18 |
| **xDD documents in snapshot** | 18,660,524 |
| **Mining cutoff date** | 2026-08-15 |
| **Initial MSc-curated terms** | 1,094 |
| **Candidate terms queued (curated + community + lexicon expansion)** | 41,688 |
| **Curated geological lexicon** | 6,242 terms (`data/geo_lexicon.txt`) |
| **Mined terms at cutoff** | 38,311 |
| **Total snippet retrievals** | 16,350,698,163 |
| **Source-token estimate (snippets × 4,326 tokens/document)** | ~70.7 trillion |
| **PostgreSQL version used** | 15.17 (Debian 15.17-1.pgdg13+1) |
| **Python version used** | 3.11 |
| **Kubernetes version used** | k3s v1.33 (single-node) |

The paper's term cohort is enumerated in its Supplementary Material S1, also
committed in the companion notebooks repository
([geonlp-paper-notebooks](https://github.com/DHeasmanGDS/geonlp-paper-notebooks),
`data/supplementary_s1_seed_terms.csv`). Per-term and per-pair statistics carry
their snapshot constants on every database row, so the published numbers remain
recoverable from a live database regardless of later mining.

## What "frozen" means

- Bug fixes are accepted only if they affect a result reported in the paper.
- Cosmetic / refactoring changes are not accepted.
- New features (e.g. additional pipeline stages) are not back-ported here.
- A companion paper (Heasman and Eglington, in preparation) may reference an
  evolved version of this codebase; that version is not included in this repository.

## What changed from v1.x to v2.0

The v1.x cut (2026-06-04) preceded the paper's final corpus build. v2.0 refreshes
`services/`, `scripts/`, `db/`, `k8s/`, `Dockerfile` and `requirements.txt` to the
2026-08-15 source state, which adds, among other things:

- the 6,242-term curated geological lexicon (`data/geo_lexicon.txt`) and the
  geology seeder / auto-queue gating built on it;
- the recalibrated term-class thresholds the paper reports
  (`TERM_CLASS_MEDIUM_MAX_HITS = 300_000`, `TERM_CLASS_LARGE_MAX_HITS = 2_000_000`,
  `SNAPSHOT_MAX_SNIPPETS_PER_TERM = 2_000_000`);
- retryable-failure requeueing in the mining worker;
- pool-scoped claiming (pools mine only their own term class) and the faster
  classifier cadence;
- the PMI-ranked network-view mode used to render the paper's Figure 4.

## Migration sequence as run on the production database

The migrations in `db/migrations/` were applied in this order during the build
of the corpus reported in the paper:

```
0001_term_requests_status.sql       (initial status/queue columns)
0002_reset_stuck_running.sql        (one-shot operational fix; idempotent no-op now)
0003_reset_fk_failures.sql          (one-shot operational fix; idempotent no-op now)
0004_term_requests_started_at.sql   (zombie detection support)
0005_term_class.sql                 (pool segregation classifier)

9999_update_probabilities.sql
9999_update_mutual_information.sql
9999_update_word_entropy.sql
9999_update_word_cooccurrence_entropy.sql
9999_update_all_statistics.sql           (orchestrator)
9999_update_all_statistics_for_term.sql  (incremental)
```

The `9999_`-prefixed files are the stored procedures as tracked in the source
tree; `db/migrations/stored_procedures/` carries the same procedures (verified
byte-identical) in the layout `db/schema.sql` includes via `\ir`, plus
`update_normalized_mi.sql`, an alternative in-database NPMI implementation that
the production system does not run (NPMI is derived at query time — see the
paper's Section 3.4).

For a fresh install, `db/schema.sql` consolidates all of the above into a
single script (preferred for new deployments).
