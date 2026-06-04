# %% [markdown]
# # 03 — PMI Walkthrough
#
# Worked example of the pointwise mutual information (PMI) computation
# described in §2.2 and §3.4 of the paper. The same formulas are
# implemented as stored procedures in `db/migrations/stored_procedures/`;
# this notebook reproduces them in plain Python to make the math
# transparent.

# %%
import math

# %% [markdown]
# ## Toy corpus
#
# Imagine a tiny snippet corpus of 1,000 snippets. We've already harvested
# and counted the following:

# %%
N = 1000  # total snippets

# Marginal counts (number of snippets containing each term)
counts = {
    'porphyry':    100,
    'epithermal':   30,
    'copper':      150,
    'skarn':        20,
    'mountain':    400,  # a high-frequency English word
    'system':      300,
}

# Joint counts (number of snippets containing both terms)
joint_counts = {
    ('porphyry', 'epithermal'):  18,
    ('porphyry', 'copper'):      75,
    ('porphyry', 'skarn'):       12,
    ('porphyry', 'mountain'):    35,
    ('porphyry', 'system'):      28,
}

# %% [markdown]
# ## Joint and marginal probabilities

# %%
def prob(word):
    return counts[word] / N

def joint_prob(w1, w2):
    return joint_counts[(w1, w2)] / N

# %% [markdown]
# ## PMI

# %%
def pmi(w1, w2):
    """log2( p(w1,w2) / (p(w1) * p(w2)) )"""
    p12 = joint_prob(w1, w2)
    p1, p2 = prob(w1), prob(w2)
    return math.log2(p12 / (p1 * p2))

# %% [markdown]
# ## NPMI (Bouma 2009)
#
# Normalized to [-1, +1] by dividing by -log2 of the joint probability.

# %%
def npmi(w1, w2):
    """PMI / -log2 p(w1, w2)"""
    p12 = joint_prob(w1, w2)
    return pmi(w1, w2) / -math.log2(p12)

# %% [markdown]
# ## Rank partners of "porphyry"

# %%
print(f"{'Partner':<12} {'p(w1,w2)':<10} {'PMI':<8} {'NPMI':<8}")
print('-' * 42)
for w2 in ['epithermal', 'copper', 'skarn', 'mountain', 'system']:
    p12 = joint_prob('porphyry', w2)
    print(f"{w2:<12} {p12:<10.4f} {pmi('porphyry', w2):<8.3f} {npmi('porphyry', w2):<8.3f}")

# %% [markdown]
# Observe:
# - `epithermal` ranks highest by PMI and NPMI even though its raw joint count is lower than `copper`. This is the value of PMI: it captures association strength, not just absolute co-occurrence.
# - `mountain` has a high joint count (35) but very low PMI because it's also very common overall. PMI correctly demotes it.
# - NPMI compresses the dynamic range. The same ordering, bounded to [-1, +1].
# - `system` shows the failure mode of low PMI on common-English partners. Filtering with a domain-aware stopword list (discussed in §5 of the paper) addresses this.

# %% [markdown]
# ## Compare to the in-database computation
#
# The stored procedures in `db/migrations/stored_procedures/` implement
# exactly these formulas in SQL. The advantage of in-database compute is
# that marginal probabilities are recomputed automatically whenever new
# terms enter the corpus, keeping the metrics consistent with the
# underlying counts at all times.
#
# Run `CALL update_all_statistics();` to recompute the entire corpus, or
# `CALL update_all_statistics_for_term('porphyry');` to recompute just
# one term's metrics incrementally.
