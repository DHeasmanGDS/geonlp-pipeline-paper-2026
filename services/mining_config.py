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

# Pre-flight gate, in xDD DOCUMENT hits (success.hits). A term above
# this is declined before mining: the worker marks the row 'failed'
# (oversized) and exits cleanly rather than OOM-killing mid-stream and
# orphaning the row. Kept == TERM_CLASS_LARGE_MAX_HITS so the classifier
# and the pre-flight gate agree on what is mineable.
#
# Calibration (2026-06-21): memory scales with SNIPPETS (~13-18 per
# doc), not docs. The 4Gi large pool handled 'reduced' (~26M snippets)
# but OOM'd on 4-8M-doc common words ('comparison' 6.2M docs -> ~100M
# snippets), leaving zombie rows that throttled the pool. Lowered from
# 10,000,000 to 2,000,000 docs (~30M snippets) so anything that would
# OOM even the 4Gi pool is declined up front. Deliberately mining a
# bigger important term (e.g. 'carbonate' ~2.07M docs) is done out of
# band via scripts/mine_one_term.py in a larger one-off pod, which
# passes skip_preflight=True to bypass this gate.
SNAPSHOT_MAX_SNIPPETS_PER_TERM = 2_000_000

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

# Term-class thresholds, in xDD DOCUMENT hits (success.hits from the
# pre-flight probe). CRITICAL CALIBRATION NOTE: a document yields ~13-18
# snippet fragments, and pod memory scales with SNIPPETS (the streaming
# Counter's vocabulary), NOT documents. So a doc-hit threshold has to be
# divided by ~15 to reason about snippet/memory load. Observed: a ~925k-
# doc term ('bei') streams ~12M snippets and OOM-kills a 1Gi small-medium
# pod; a ~977k-doc term ('ein') streamed ~18M before OOM. The old medium
# ceiling of 1,000,000 docs therefore routed ~13-18M-snippet terms into
# the 1Gi pool, which OOM'd them on a loop (the janitor re-queues a
# reaped zombie with its class intact -> re-claimed -> re-OOM).
#
#   small      hits <        100,000    fast (<30 min), 1Gi
#   medium     hits <        300,000    ~4-5M snippets, safe in 1Gi
#   large      hits <      2,000,000    4Gi pod + pruning (~26M snippets)
#   oversized  hits >=     2,000,000    declined (OOMs even the 4Gi pool)
#
# Large-pool ceiling lowered 10M -> 2M docs (2026-06-21): 2-8M-doc common
# words stream 30-110M snippets and OOM'd even the 4Gi pool, leaving
# zombie rows that held the cap and throttled the pool. Anything bigger
# is now declined at classification. A deliberately-important oversized
# term is mined out of band (scripts/mine_one_term.py, bigger pod). The
# durable fix for the recurring noise is curating the contributor-bot's
# input to geoscience terms, not raising thresholds.
TERM_CLASS_SMALL_MAX_HITS = 100_000
TERM_CLASS_MEDIUM_MAX_HITS = 300_000   # lowered from 1,000,000 — see snippet/doc note above
TERM_CLASS_LARGE_MAX_HITS = 2_000_000  # == SNAPSHOT_MAX_SNIPPETS_PER_TERM by design

# All known classes, in order of increasing workload size.
TERM_CLASSES = ("small", "medium", "large", "oversized")


# Per-pool upper bound on simultaneously-mining pods. With
# `concurrencyPolicy: Allow` on each CronJob, K8s imposes no cap of its
# own, so the worker enforces these as a soft DB-level check in
# scripts/process_pending_terms.py::main(). They live here (not in the
# worker script) so the Request-a-term page can surface them read-only —
# that way the displayed cap can never drift from the enforced one.
#
# Sizing (production NUC, 15.5 GiB / 8 cores):
#   small-medium: 25 x 1Gi pods  (~10 GiB working set in practice)
#   large       :  5 x 4Gi pods  (~12 GiB working set; wider vocab)
# The two pools rarely saturate together, and large-pool peak is bounded
# by in-stream pruning. If `kubectl top node` shows sustained memory
# > 85% under both pools busy, drop MAX_CONCURRENT_SMALL_MEDIUM first
# (small terms drain fastest so the queue recovers quickly).
MAX_CONCURRENT_SMALL_MEDIUM = 25
MAX_CONCURRENT_LARGE = 5

# Legacy single-pool cap, used when a worker runs without --class
# (matches pre-Phase-1 behavior).
MAX_CONCURRENT_MINERS = 30


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
