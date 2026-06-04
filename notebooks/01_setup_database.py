# %% [markdown]
# # 01 — Setup Database
#
# This notebook walks through provisioning a fresh PostgreSQL database for
# the geonlp pipeline described in Heasman & Eglington (2026).
#
# Prerequisites:
# - PostgreSQL 15+ installed and running
# - psql available on PATH
# - A database role with CREATEDB privilege (or an existing empty database)

# %% [markdown]
# ## Step 1 — Create the database (skip if you already have an empty geonlp_db)

# %%
# !createdb geonlp_db

# %% [markdown]
# ## Step 2 — Apply the consolidated schema

# %%
# !psql -d geonlp_db -f ../db/schema.sql

# %% [markdown]
# ## Step 3 — Apply stored procedures
#
# These compute the derived columns (probability, mutual_information, NPMI,
# entropy) in-database from raw counts.

# %%
import subprocess
import pathlib

sp_dir = pathlib.Path("../db/migrations/stored_procedures")
for sp_file in sorted(sp_dir.glob("*.sql")):
    print(f"Applying {sp_file.name}...")
    subprocess.run(["psql", "-d", "geonlp_db", "-f", str(sp_file)], check=True)

# %% [markdown]
# ## Step 4 — Verify the schema

# %%
# !psql -d geonlp_db -c "\d+"

# %% [markdown]
# You should see the four tables:
# - `processed_terms`
# - `term_counts`
# - `term_cooccurrence` (with 32 partitions)
# - `term_requests`
#
# And the six stored procedures:
# - `update_probabilities()`
# - `update_mutual_information()`
# - `update_word_entropy()`
# - `update_word_cooccurrence_entropy()`
# - `update_all_statistics()`
# - `update_all_statistics_for_term(text)`

# %% [markdown]
# ## Step 5 — Configure environment
#
# Copy `.env.example` to `.env` at the repo root and fill in your DB credentials.
# These are loaded automatically by any script that imports
# `services.database.get_engine`.

# %%
# !cp ../.env.example ../.env
# Then edit ../.env

# %% [markdown]
# ## Step 6 — Smoke test
#
# Submit a single small term to confirm everything works end-to-end.

# %%
# !psql -d geonlp_db -c "INSERT INTO term_requests (term) VALUES ('quesnellia');"
# !cd .. && python scripts/process_pending_terms.py
