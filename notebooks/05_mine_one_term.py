# %% [markdown]
# # 05 — Mine One Term End-to-End
#
# Demonstrates the full mining pipeline by harvesting a small term and
# inspecting the results. Use a niche term so the mine completes in
# a couple of minutes rather than hours.
#
# Prerequisites:
# - You've run notebook 01 (database is set up)
# - .env is configured with your DB credentials
# - You have internet access to reach https://xdd.wisc.edu/api/snippets

# %%
import sys
sys.path.insert(0, '..')

import os
from sqlalchemy import text
from services.database import get_engine

# %% [markdown]
# ## Step 1 — Queue a niche term
#
# We use a term that's specific enough to return a manageable corpus
# (~1,000 snippets) so the demo completes quickly.

# %%
TERM = "quesnellia"   # a tectonostratigraphic terrane in BC, Canada

engine = get_engine()
with engine.begin() as conn:
    conn.execute(
        text("INSERT INTO term_requests (term) VALUES (:t) ON CONFLICT DO NOTHING"),
        {"t": TERM},
    )
print(f"Queued: {TERM}")

# %% [markdown]
# ## Step 2 — Run the worker
#
# This invokes the actual production script. It pre-flight checks xDD,
# claims the term, streams snippets, accumulates counts (with optional
# in-stream pruning), computes co-occurrence, and persists results.

# %%
# !cd .. && python scripts/process_pending_terms.py

# %% [markdown]
# Watch the log lines. You should see:
# - `[xdd] '<term>': starting harvest from https://xdd.wisc.edu/api/snippets`
# - Pre-flight hit count
# - Periodic progress lines (`[xdd] '<term>': page N, M snippets streamed so far`)
# - `[worker] '<term>': N snippets streamed, M unique lemmas counted`
# - `[worker] '<term>' DONE in X.X min`

# %% [markdown]
# ## Step 3 — Inspect the results

# %%
import pandas as pd

# Verify the term is now in processed_terms
with engine.connect() as conn:
    row = conn.execute(
        text("SELECT term, processed_at FROM processed_terms WHERE term = :t"),
        {"t": TERM},
    ).fetchone()
print(f"Mined: {row}")

# Get the term's marginal count
with engine.connect() as conn:
    row = conn.execute(
        text("""
            SELECT word, count, probability, mining_max_acquired
            FROM term_counts
            WHERE word = :t
        """),
        {"t": TERM},
    ).fetchone()
print(f"\nTerm row: {row}")

# Top-20 co-occurring partners by PMI
with engine.connect() as conn:
    df = pd.read_sql(
        text("""
            SELECT
                word_2,
                count,
                ROUND(prob_w1w2::numeric, 6) AS prob_w1w2,
                ROUND(mutual_information::numeric, 3) AS pmi_bits,
                ROUND(normalized_mi::numeric, 3) AS npmi
            FROM term_cooccurrence
            WHERE word_1 = :t
            ORDER BY mutual_information DESC NULLS LAST
            LIMIT 20
        """),
        conn,
        params={"t": TERM},
    )

print(f"\nTop-20 partners of '{TERM}' by PMI:")
print(df.to_string(index=False))

# %% [markdown]
# ## Step 4 — What this demonstrates
#
# Each row in `term_counts` and `term_cooccurrence` carries the snapshot
# provenance fields (`mining_max_acquired`, `mining_total_docs`,
# `mining_tokens_per_doc`) so you can distinguish cohorts mined under
# different xDD snapshots. The same fields appear on every row written
# by every mine, allowing reproducibility audits and snapshot-aware queries.
#
# To mine more terms, queue them in `term_requests` and run the worker
# again. In production, the worker runs as a CronJob (see `k8s/`) with
# `--class small,medium` or `--class large` to scope itself to one of
# the two worker pools.
