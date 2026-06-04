"""Mining corpus snapshot configuration.

These constants are PINNED to a point-in-time snapshot of xDD so that
statistics across terms remain comparable. Re-deriving them from
current xDD state would mean an old term mined a year ago and a new
term mined today would compute probabilities against different
denominators — breaking comparability for rare terms.

Two parameters are critical for reproducibility:

  - max_acquired (NOT max_published): filters by xDD's ingest date,
    not the journal's publication date. A paper published in 2010 but
    only acquired by xDD in 2025 would slip into a max_published-only
    filter — wrong. max_acquired pins us to "the set of papers xDD had
    on this date," which is the snapshot we actually built against.

  - fragment_limit: max snippets returned per document. Without this,
    xDD's default (subject to change) silently shifts the count of
    snippets per paper — and therefore the count of co-occurrences.

Common-term probabilities (water, mineral, etc.) barely move when
the snapshot is updated; rare-term probabilities can shift by tens of
percent. The constants below match the MSc-notebook xDD call used to
build the original corpus.

To rebuild the corpus against a newer xDD snapshot:
  1. Update SNAPSHOT_MAX_ACQUIRED to the new cutoff date.
  2. Look up xDD's total article count at that acquired-date and put
     it in SNAPSHOT_TOTAL_DOCS.
  3. (Optional) Drop processed_terms, term_counts, term_cooccurrence
     and re-queue every prior term. New mines will use the new
     snapshot consistently.

In normal operation, leave these constants alone.
"""

# Cutoff date for xDD's INGEST timestamp (acquired_at), NOT the
# journal publication date. Format: YYYY-MM-DD.
#
# History:
#   2023-01-01: MSc-thesis snapshot. ~16M docs. (Original 1100-term corpus.)
#   2026-05-18: Full rebuild snapshot. ~18.6M docs. Triggered by a
#               schema migration that added mining_max_acquired columns
#               so future refreshes can be diffed rather than wiped.
SNAPSHOT_MAX_ACQUIRED = "2026-05-18"

# Total xDD articles acquired before SNAPSHOT_MAX_ACQUIRED.
# Verify against existing term_counts via:
#   SELECT word, count, probability,
#          (count::numeric / probability / mining_tokens_per_doc)::bigint AS implied_total_docs
#   FROM term_counts
#   WHERE count > 1000 AND probability > 0
#   ORDER BY count DESC LIMIT 5;
# All implied_total_docs values should match (or come very close to)
# this constant for rows mined under this snapshot version.
SNAPSHOT_TOTAL_DOCS = 18_660_524

# Average tokens per indexed article. Used together with
# SNAPSHOT_TOTAL_DOCS as the global token-count denominator.
SNAPSHOT_TOKENS_PER_DOCUMENT = 4326

# Max snippets xDD will return per article. Matches the MSc notebook
# call so per-article snippet caps are deterministic across mines.
# (Without this, xDD's default applies and can change silently.)
SNAPSHOT_FRAGMENT_LIMIT = 2000

# Hard upper limit on snippets we'll mine for a single term. Above this,
# the streaming Counter's unique-token vocabulary exceeds the 1Gi pod
# memory limit and the worker OOMKills mid-mine — creating a zombie
# row. Pre-flight check probes xDD's `success.hits` field BEFORE
# claiming the term; if hits > this threshold, the worker marks the
# row `failed` with a terminal error and exits cleanly. No OOM, no
# zombie, honest reporting.
#
# Calibration: at ~250 bytes per unique lemma in Python's Counter,
# a 1Gi memory budget holds roughly 4M unique partner tokens before
# headroom is gone. Empirically, high-frequency terms tend to have
# a partner-vocab : snippet-count ratio of around 1:5, so a 20M
# snippet threshold leaves comfortable headroom. We use 10M for
# a safety margin against unusually-wide vocabularies.
SNAPSHOT_MAX_SNIPPETS_PER_TERM = 10_000_000

# In-stream Counter pruning thresholds.
#
# For very common terms (>5M unique partner tokens), the streaming
# Counter can exceed the pod memory limit during the harvest phase,
# OOM-killing the pod before mining completes. To bound memory, the
# worker periodically prunes low-frequency entries from the Counter —
# tokens appearing fewer than SNAPSHOT_PRUNE_KEEP_MIN times across
# all snippets streamed so far. Such tokens have near-zero PMI by
# construction and would not appear in the top-N partner ranking.
#
# This is a lossy operation: pruned tokens are unrecoverable for the
# current mine. The trade-off — losing tail-end vocabulary in exchange
# for being able to mine mega-frequency terms at all — is documented
# in §5 of the methodology paper.

# How often (in snippets streamed) to check whether pruning is needed.
SNAPSHOT_PRUNE_CHECK_INTERVAL = 500_000

# Prune when Counter vocabulary exceeds this many unique tokens.
SNAPSHOT_PRUNE_TRIGGER_SIZE = 5_000_000

# When pruning, drop entries with raw count below this value.
SNAPSHOT_PRUNE_KEEP_MIN = 5

# Term-class thresholds.
#
# These define the boundaries between worker pools. A term's xDD
# snippet count (success.hits from the pre-flight probe) is mapped to
# one of four classes; the workers claim from the queue filtered by
# their allowed class set:
#
#   small      hits <         100,000    fast (<30 min)
#   medium     hits <       1,000,000    moderate (a few hours)
#   large      hits <      10,000,000    slow (24h+), needs 4Gi pod + pruning
#   oversized  hits >=     10,000,000    declined (would OOM even with pruning)
#
# The 'oversized' bound is identical to SNAPSHOT_MAX_SNIPPETS_PER_TERM
# so the pre-flight check and the classifier agree on what's mineable.
#
# Tune these by watching mining-time distributions per class. If
# 'medium' terms routinely take more than a few hours, lower
# TERM_CLASS_MEDIUM_MAX_HITS so they get routed to the large pool with
# its bigger memory budget. If 'small' is too sparse, raise its
# threshold to absorb more terms.
TERM_CLASS_SMALL_MAX_HITS = 100_000
TERM_CLASS_MEDIUM_MAX_HITS = 1_000_000
TERM_CLASS_LARGE_MAX_HITS = 10_000_000  # == SNAPSHOT_MAX_SNIPPETS_PER_TERM by design

# All known classes, in order of increasing workload size.
TERM_CLASSES = ("small", "medium", "large", "oversized")


def classify_hits(hits: int | None) -> str | None:
    """Map an xDD `success.hits` count to a term class name.

    Returns None when `hits` is None (e.g., xDD was unreachable when
    the classifier probed); the caller should leave the row
    unclassified rather than guess.

    Boundary convention: a term whose hit count exactly equals a
    threshold falls into the LARGER class (e.g., hits == 100_000 is
    'medium', not 'small'). This is the conservative direction —
    workloads that sit on a boundary get the bigger memory budget.
    """
    if hits is None:
        return None
    if hits < TERM_CLASS_SMALL_MAX_HITS:
        return "small"
    if hits < TERM_CLASS_MEDIUM_MAX_HITS:
        return "medium"
    if hits < TERM_CLASS_LARGE_MAX_HITS:
        return "large"
    return "oversized"


def total_tokens() -> int:
    """Full-corpus token count = denominator for probability calcs."""
    return SNAPSHOT_TOTAL_DOCS * SNAPSHOT_TOKENS_PER_DOCUMENT


def xdd_snapshot_params() -> dict:
    """xDD query parameters that pin every mining request to the
    snapshot. Pass via `extra_params=` to iter_snippets /
    harvest_snippets so every page request to xDD carries them.
    """
    return {
        "max_acquired": SNAPSHOT_MAX_ACQUIRED,
        "fragment_limit": str(SNAPSHOT_FRAGMENT_LIMIT),
    }
