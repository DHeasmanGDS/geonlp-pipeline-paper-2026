# Files to copy from your working tree

The files I drafted are in this directory and ready to commit. The
following files already exist in your working tree at
`C:\Claude Files\python\geo_nlp_portal\` and should be **copied as-is**
into the new repo at the indicated paths.

## Source code (copy from `C:\Claude Files\python\geo_nlp_portal\`)

| Source file | Destination in new repo |
|---|---|
| `services/mining_config.py` | `services/mining_config.py` |
| `services/mining/__init__.py` | `services/mining/__init__.py` |
| `services/mining/cooccurrence.py` | `services/mining/cooccurrence.py` |
| `services/mining/xdd_harvester.py` | `services/mining/xdd_harvester.py` |
| `services/mining/text_processing.py` | `services/mining/text_processing.py` |
| `services/mining/term_classifier.py` | `services/mining/term_classifier.py` |
| `scripts/process_pending_terms.py` | `scripts/process_pending_terms.py` |
| `scripts/classify_pending_terms.py` | `scripts/classify_pending_terms.py` |
| `scripts/reset_zombies.py` | `scripts/reset_zombies.py` |
| `scripts/apply_migration.py` | `scripts/apply_migration.py` |

## Database migrations (copy from `db/migrations/` in working tree)

| Source file | Destination |
|---|---|
| `db/migrations/0001_term_requests_status.sql` | `db/migrations/0001_term_requests_status.sql` |
| `db/migrations/0002_reset_stuck_running.sql` | `db/migrations/0002_reset_stuck_running.sql` |
| `db/migrations/0003_reset_fk_failures.sql` | `db/migrations/0003_reset_fk_failures.sql` |
| `db/migrations/0004_term_requests_started_at.sql` | `db/migrations/0004_term_requests_started_at.sql` |
| `db/migrations/0005_term_class.sql` | `db/migrations/0005_term_class.sql` |

## Stored procedures (rename from `9999_*.sql` to clean names)

These currently sit in `db/migrations/` with the `9999_` prefix in your
working tree. I'd suggest renaming them when copying:

| Source file | Destination |
|---|---|
| `db/migrations/9999_update_probabilities.sql` | `db/migrations/stored_procedures/update_probabilities.sql` |
| `db/migrations/9999_update_mutual_information.sql` | `db/migrations/stored_procedures/update_mutual_information.sql` |
| `db/migrations/9999_update_word_entropy.sql` | `db/migrations/stored_procedures/update_word_entropy.sql` |
| `db/migrations/9999_update_word_cooccurrence_entropy.sql` | `db/migrations/stored_procedures/update_word_cooccurrence_entropy.sql` |
| `db/migrations/9999_update_all_statistics.sql` | `db/migrations/stored_procedures/update_all_statistics.sql` |
| `db/migrations/9999_update_all_statistics_for_term.sql` | `db/migrations/stored_procedures/update_all_statistics_for_term.sql` |

If you have an NPMI stored procedure, add it too:

| Source file | Destination |
|---|---|
| `db/migrations/9999_update_normalized_mi.sql` (if exists) | `db/migrations/stored_procedures/update_normalized_mi.sql` |

## Kubernetes manifests (copy from `k8s/`)

| Source file | Destination |
|---|---|
| `k8s/geonlp-cronjob.yaml` | `k8s/geonlp-cronjob.yaml` |
| `k8s/geonlp-cronjob-large.yaml` | `k8s/geonlp-cronjob-large.yaml` |
| `k8s/geonlp-classifier-cronjob.yaml` | `k8s/geonlp-classifier-cronjob.yaml` |
| `k8s/geonlp-janitor-cronjob.yaml` | `k8s/geonlp-janitor-cronjob.yaml` |
| `k8s/geonlp-stats-cronjob.yaml` | `k8s/geonlp-stats-cronjob.yaml` |
| `k8s/apply-migration-job.yaml` | `k8s/apply-migration-job.yaml` |

(NOT `k8s/geonlp-deployment.yaml` — that's the web app, which you're not sharing.)

## Files I drafted (already in this directory, ready to copy)

| File | Status |
|---|---|
| `README.md` | Drafted, review and tweak as needed |
| `STATE.md` | Drafted, fill in `[FILL IN]` placeholders |
| `LICENSE` | Drafted, year and authors set to 2026/Heasman+Eglington |
| `.gitignore` | Drafted, comprehensive Python + secrets + IDE coverage |
| `.env.example` | Drafted, no real credentials |
| `requirements.txt` | Drafted, pinned to current stable versions |
| `Dockerfile` | Drafted, mirrors what your production image would look like |
| `db/schema.sql` | Drafted, consolidated schema from migration sequence — **verify column types and constraints match your actual DB before publishing** |
| `k8s/README.md` | Drafted, explains pool segregation and deployment topology |
| `notebooks/*.py` | 5 demonstration notebooks in Jupytext format |
| `notebooks/README.md` | Explains the notebook format and conversion |

## Security audit checklist (run before pushing)

After copying everything in, from the repo root run:

```bash
# Check for accidentally committed secrets
git grep -i -E "(password|secret|api[_-]?key|token|bearer)" -- ':!*.md' ':!*.example'

# Check for hardcoded internal IPs / hostnames
git grep -E "192\.168\." -- ':!*.md'
git grep -E "10\.42\." -- ':!*.md'
git grep -i -E "(k3s-master|nuc)" -- ':!*.md'

# Verify .env is ignored
git check-ignore -v .env || echo "WARNING: .env not in .gitignore"

# Strip any Jupyter outputs (defensive — your .py files don't have them, but just in case)
find . -name "*.ipynb" -exec jupyter nbconvert --clear-output --inplace {} \;
```

Address anything those greps surface before `git push`.

## Suggested git workflow

```bash
# Initialize repo locally
cd path/to/new/geonlp-pipeline-paper-2026
git init
git add .
git commit -m "Initial snapshot accompanying Heasman & Eglington (2026)"

# Create the GitHub repo (via web or gh CLI)
gh repo create DHeasmanGDS/geonlp-pipeline-paper-2026 \
    --public \
    --source=. \
    --description "Frozen code snapshot accompanying Heasman & Eglington (2026), Computers & Geosciences"

git push -u origin main

# Tag the snapshot for stable citation
git tag -a v1.0 -m "Paper submission snapshot — Heasman & Eglington (2026)"
git push origin v1.0
```

After pushing, get the **DOI for the tag** via Zenodo:
1. Sign in to https://zenodo.org with your GitHub account
2. Go to https://zenodo.org/account/settings/github/
3. Enable the toggle for `DHeasmanGDS/geonlp-pipeline-paper-2026`
4. Create a release on GitHub (use the v1.0 tag)
5. Zenodo will mint a DOI for that release
6. Update the README citation block with the DOI
