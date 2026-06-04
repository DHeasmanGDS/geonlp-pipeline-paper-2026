# geonlp-pipeline-paper-2026

Frozen code snapshot accompanying:

> Heasman, D. and Eglington, B. (2026). A Reproducible Pipeline for
> Constructing Domain-Specific Text Corpora from Scholarly Literature:
> A Case Study in Geoscience Using the xDD Snippet API.
> *Computers & Geosciences*, [in review].
> DOI: [to be added on acceptance]

This repository contains the production pipeline source code, database
schema, and Kubernetes deployment manifests described in the paper,
plus Jupyter notebooks demonstrating each component.

It is a **frozen snapshot** of the codebase as of paper submission.
For the actively-evolving codebase, contact the corresponding author
(see Contact below).

## Repository contents

| Path | What's in it |
|---|---|
| `services/mining/` | Algorithmic core: xDD harvest, preprocessing, PMI computation, in-stream Counter pruning, term classification |
| `services/mining_config.py` | Pinned snapshot constants and classifier thresholds |
| `scripts/` | Entry points: mining worker, classifier, zombie janitor |
| `db/schema.sql` | Consolidated PostgreSQL schema for fresh installs |
| `db/migrations/` | Numbered migration files capturing schema evolution |
| `db/migrations/stored_procedures/` | In-database PMI / entropy compute procedures |
| `k8s/` | Kubernetes CronJob manifests for the worker pools, classifier, and janitor |
| `notebooks/` | Guided demonstrations of each pipeline component |
| `requirements.txt` | Pinned Python dependencies |
| `Dockerfile` | Container build for the mining workers |
| `.env.example` | Template for database credentials (NEVER commit a real `.env`) |

## What this repository does NOT contain

For clarity about scope:

- **The companion web application** (FastAPI service backing `app.terra-datasystems.com`) is intentionally not included. The pipeline described in this paper runs independently of the web application; source is available from the corresponding author on request.
- **The live evolving codebase** is private. This snapshot reflects the state at paper submission only. Subsequent improvements, bug fixes, and feature additions are not back-ported here.
- **The xDD snippet data itself** is not included (Creative Commons Attribution-NonCommercial 4.0 licensing). See the paper's Data Availability section for licensing details.

## Reproduction

### Quick start (single workstation)

1. **Provision PostgreSQL 15+ locally**, with a database named `geonlp_db` and a user with full privileges.

2. **Apply the schema**:
   ```bash
   psql -d geonlp_db -f db/schema.sql
   ```
   Or, to mirror the migration history exactly:
   ```bash
   for f in db/migrations/0001_*.sql db/migrations/0004_*.sql db/migrations/0005_*.sql; do
       psql -d geonlp_db -f "$f"
   done
   for f in db/migrations/stored_procedures/*.sql; do
       psql -d geonlp_db -f "$f"
   done
   ```

3. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   python -c "import nltk; nltk.download('wordnet'); nltk.download('stopwords')"
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your DB credentials
   ```

5. **Queue a term and run the worker**:
   ```bash
   psql -d geonlp_db -c "INSERT INTO term_requests (term) VALUES ('porphyry');"
   python scripts/process_pending_terms.py
   ```

   The worker will pre-flight check xDD, claim the term, stream snippets, compute counts and co-occurrence, and persist results.

### Production deployment (Kubernetes)

The `k8s/` directory contains CronJob manifests for parallelized mining at scale. See `k8s/README.md` for the deployment topology.

### Reproducing the paper's specific results

See `notebooks/` for guided walkthroughs:

- `01_setup_database.ipynb` — schema setup from scratch
- `02_preprocess_demo.ipynb` — tokenization and lemmatization of sample snippets
- `03_pmi_walkthrough.ipynb` — PMI computation worked example
- `04_in_stream_pruning_demo.ipynb` — Strategy A (in-stream Counter pruning) demonstration
- `05_mine_one_term.ipynb` — full end-to-end mine of a small term

The paper's specific tables and figures are reproduced in a companion repository: [geonlp-paper-notebooks](https://github.com/DHeasmanGDS/geonlp-paper-notebooks).

## Pipeline architecture (in brief)

```
xDD Snippet API
       |
       v
Python Harvester ── pre-flight hit check (skip if hits > 10M)
       |               retries with backoff (network resilience)
       |               BibJSON bibliography generation
       v
Text Preprocessor ── tokenize, stopword removal, NLTK lemmatize
       |               in-stream Counter pruning (Strategy A)
       v
PostgreSQL Database
       |   - processed_terms (audit log)
       |   - term_counts (per-term counts, probabilities, snapshot provenance)
       |   - term_cooccurrence (32-partition hash-partitioned, PMI, NPMI, entropy)
       |   - term_requests (pool-segregated queue: small / medium / large / oversized)
       |   - Stored procedures compute PMI, NPMI, joint entropy in-database
       v
Downstream consumers (notebooks, web app)
```

See Figure 1 in the paper for the full architecture diagram.

## Key constants (from `services/mining_config.py`)

```python
SNAPSHOT_MAX_ACQUIRED = "2026-05-18"     # xDD ingest cutoff
SNAPSHOT_TOTAL_DOCS = 18_660_524         # xDD document count at cutoff
SNAPSHOT_TOKENS_PER_DOCUMENT = 4326       # average tokens per indexed article
SNAPSHOT_FRAGMENT_LIMIT = 2000            # max snippets per article in API call
SNAPSHOT_MAX_SNIPPETS_PER_TERM = 10_000_000   # oversized class threshold
SNAPSHOT_PRUNE_CHECK_INTERVAL = 500_000   # snippets between pruning checks
SNAPSHOT_PRUNE_TRIGGER_SIZE = 5_000_000   # Counter size triggering prune
SNAPSHOT_PRUNE_KEEP_MIN = 5               # minimum count to retain
```

Adjust these to re-mine against a different xDD snapshot or to tune memory behaviour on different hardware.

## Citation

If you use this code or build on the pipeline described in the paper, please cite:

```bibtex
@article{Heasman2026,
  author  = {Heasman, Drew and Eglington, Bruce},
  title   = {A Reproducible Pipeline for Constructing Domain-Specific Text
             Corpora from Scholarly Literature: A Case Study in Geoscience
             Using the xDD Snippet API},
  journal = {Computers \& Geosciences},
  year    = {2026},
  note    = {[in review]},
  doi     = {[to be added on acceptance]}
}
```

Please also cite xDD itself:

```bibtex
@article{Peters2023,
  author  = {Peters, S.E. and Ross, I.A. and Rekatsinas, M.L.},
  title   = {xDD: a platform for text and data mining from scholarly publications},
  year    = {2023}
}
```

## License

MIT. See `LICENSE`.

Data outputs derived from xDD (snippets, BibJSON files, and aggregate metric tables) are governed by xDD's Creative Commons Attribution-NonCommercial 4.0 licence (CC BY-NC 4.0) — not the MIT license of this code.

## Contact

Drew Heasman, Department of Geological Sciences, University of Saskatchewan.
Email: heasman.drew@gmail.com.
