"""Shared information-theoretic helpers used by routes that display
per-pair metrics from `term_cooccurrence`.

The `mutual_information` column on `term_cooccurrence` is computed by
the Postgres proc `update_mutual_information()` as:

    prob_w1w2 * LOG(prob_w1w2 / (p1 * p2)) / LN(2)

That formula has two quirks worth knowing about before consuming the
column:

1. It's **weighted by `prob_w1w2`** — the value is the per-pair
   contribution to total mutual information, not the per-pair PMI.
   Per-pair PMI is recovered by dividing by `prob_w1w2`.

2. **Postgres `LOG()` is base-10**, not natural log. So the SQL
   result is in "mixed units" — off from the desired bits-form by a
   factor of `ln(10)`. The stored value is `0.4343 × true_bits`.
   This appears to be a typo in the original SQL (should be LN/LN(2)
   for log_2, not LOG/LN(2)); fixing it server-side would require
   rewriting the proc and re-running update_all_statistics over the
   ~9GB partitioned table. The Python helpers below compensate in
   the meantime — see ARCHITECTURE_REVIEW.md item 22.

For NPMI:
    NPMI = PMI / -log2(P(x,y))  ∈  [-1, 1]
         where PMI = log2(P(x,y) / (P(x)P(y)))

Recovering true NPMI from the stored mixed-unit value:
    PMI_bits = stored * ln(10) / prob_w1w2
    NPMI     = PMI_bits / -log2(prob_w1w2)
             = stored * ln(10) / (prob_w1w2 * -log2(prob_w1w2))
"""

from __future__ import annotations

import math
from typing import Optional

# Conversion factor between the stored mixed-unit value and proper bits.
# The SQL uses LOG()/LN(2) which is log_10(x) / ln(2); the desired
# base-2 log would be LN(x) / LN(2). The ratio is ln(10).
_BIT_SCALE = math.log(10)


def compute_pmi_bits(prob_w1w2, mi_contribution) -> Optional[float]:
    """True per-pair pointwise mutual information in bits.

    Returns None when the inputs are missing / zero. Otherwise the
    result is in (-∞, +∞) — typical magnitudes for geological terms
    are 0 to 10+ bits.
    """
    if mi_contribution is None or prob_w1w2 is None or prob_w1w2 <= 0:
        return None
    return float(mi_contribution) * _BIT_SCALE / float(prob_w1w2)


def network_partner_sql(order: str) -> str:
    """SQL for a term's top-N co-occurrence partners, ranked by `order`.

    'count' — raw co-occurrence count (the network view's default).
    'pmi'   — per-pair PMI: the stored mutual_information is the
              probability-weighted MI contribution, so dividing by
              prob_w1w2 recovers per-pair PMI up to a constant factor
              (ln 10), which cannot change the ordering. A count floor
              keeps one-off rare pairs (PMI's known failure mode) out
              of the graph.

    Only fixed strings are interpolated — `order` is validated against
    a closed set here AND by the route's Query pattern.
    """
    if order == "pmi":
        return """
            SELECT word_2, count, prob_w1w2, mutual_information
            FROM term_cooccurrence
            WHERE word_1 = :t AND count >= 25 AND prob_w1w2 > 0
            ORDER BY (mutual_information / prob_w1w2) DESC NULLS LAST
            LIMIT :limit
        """
    if order != "count":
        raise ValueError(f"unknown partner ranking: {order!r}")
    return """
        SELECT word_2, count, prob_w1w2, mutual_information
        FROM term_cooccurrence
        WHERE word_1 = :t
        ORDER BY count DESC
        LIMIT :limit
    """


def compute_npmi(prob_w1w2, mi_contribution) -> Optional[float]:
    """Normalized pointwise mutual information, bounded in [-1, 1].

    - NPMI = 1  : the pair always occurs together
    - NPMI = 0  : the pair occurs as expected by chance
    - NPMI = -1 : the pair never occurs together

    Returns None when the math is undefined (missing inputs, zero
    probability, or p=1 which makes the denominator zero).
    """
    if mi_contribution is None or prob_w1w2 is None or prob_w1w2 <= 0:
        return None
    denom = -math.log2(prob_w1w2)
    if denom <= 0:
        return None
    return float(mi_contribution) * _BIT_SCALE / (float(prob_w1w2) * denom)
