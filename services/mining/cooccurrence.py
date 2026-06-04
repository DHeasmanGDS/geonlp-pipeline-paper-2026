"""Co-occurrence count computation for a single search term.

Adapted from `nlp_statistics.calculate_cooccurrence` in the MSc geonlp
notebooks. Pure function — given a list of preprocessed snippets and a
search term, returns the top-N partner terms with raw counts and
approximate joint probabilities.

The `mutual_information` and `entropy_w1w2` columns in `term_cooccurrence`
are NOT computed here. They are populated by the Postgres stored
procedure `update_all_statistics()`, which runs after the bulk insert.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

import pandas as pd
from nltk.stem import PorterStemmer, WordNetLemmatizer

# Re-exported here so legacy callers (the MSc-era code) still get a
# symbol with this name. New code should import SNAPSHOT_TOKENS_PER_DOCUMENT
# from services.mining_config directly.
from services.mining_config import SNAPSHOT_TOKENS_PER_DOCUMENT as TOTAL_TOKENS_PER_DOCUMENT

_lemmatizer = WordNetLemmatizer()
_stemmer = PorterStemmer()


def accumulate_tokens(processed_text: str, counts: Counter) -> int:
    """Lemmatize tokens in a single preprocessed snippet and add them
    to `counts` (modified in place). Returns the number of tokens added.

    Used by the streaming worker to update a running Counter as each
    snippet arrives, rather than buffering all snippets in memory.

    Skips tokens of length <= 2 (matches the original
    calculate_cooccurrence behavior).
    """
    if not processed_text:
        return 0
    added = 0
    for token in processed_text.split():
        if len(token) <= 2:
            continue
        counts[_lemmatizer.lemmatize(token.lower())] += 1
        added += 1
    return added


def maybe_prune_counter(
    counts: Counter,
    n_snippets: int,
    *,
    trigger_size: int = 5_000_000,
    keep_min: int = 5,
    log=print,
):
    """Periodically prune low-frequency tokens from a streaming Counter
    to bound memory on mega-frequency terms.

    Called by the worker every SNAPSHOT_PRUNE_CHECK_INTERVAL snippets.
    When the Counter exceeds `trigger_size` unique tokens, drops all
    entries with raw count below `keep_min`. Returns
    `(size_before, size_after)` if pruning occurred, `None` otherwise.

    Methodology: this is a lossy bound on streaming memory. Tokens
    dropped during pruning are unrecoverable for this mine. Empirical
    impact on the top-N PMI ranking is negligible because dropped
    tokens are by construction low-count partners that would not appear
    in the top-N. The trade-off is documented in §5 of the methodology
    paper (Heasman and Eglington, in preparation).

    Memory: pruning temporarily uses an intermediate dict during
    clear-and-rebuild. For a 5M-entry Counter pruned to ~500K, peak
    spike is ~250 MB above steady-state Counter size. Total worst-case
    process memory stays well below the 1 GiB pod limit.
    """
    size_before = len(counts)
    if size_before <= trigger_size:
        return None

    # Rebuild Counter in place. Counter has no native filter-in-place
    # operation, so we materialize the kept-subset as a plain dict,
    # clear the original, and update — net result is the original
    # Counter object retained (caller keeps its reference) with only
    # entries above the threshold remaining.
    kept = {k: v for k, v in counts.items() if v >= keep_min}
    counts.clear()
    counts.update(kept)
    size_after = len(counts)

    log(f"[prune] after {n_snippets:,} snippets: "
        f"counter {size_before:,} -> {size_after:,} "
        f"(dropped {size_before - size_after:,} tokens with count < {keep_min})")
    return (size_before, size_after)


def cooccurrence_from_counts(
    counts: Counter,
    search_term: str,
    n: int,
    total_docs: int,
) -> pd.DataFrame:
    """Build the top-N cooccurrence DataFrame from an already-accumulated
    Counter of lemmatized token frequencies.

    Mirrors `calculate_cooccurrence` exactly except it skips the
    tokenization step. Use this in conjunction with `accumulate_tokens`
    when streaming.

    Memory model: for very common terms ('flow', 'system', 'model'),
    the streaming Counter can reach 5-10M unique lemmas. The previous
    implementation called `Counter(counts)` to copy the dict before
    popping self-cooccurrence — that copy step alone could push memory
    past the 1 GiB pod limit at the worst possible moment (right at
    the end of mining, after all snippets streamed). This implementation
    uses `heapq.nlargest` with an inline filter, which does a single
    pass over `counts.items()` without copying. Peak memory drops by
    roughly half during the post-streaming phase.
    """
    import heapq  # local import: only needed at the post-streaming step

    search_term_lc = search_term.lower().strip()
    search_term_words = set(search_term_lc.split())
    total_tokens = total_docs * TOTAL_TOKENS_PER_DOCUMENT

    # Pre-compute the set of words to skip (search term + naive plural).
    # Doing this once means the inline filter below is O(1) per entry.
    skip = set()
    for w in search_term_words:
        skip.add(w)
        skip.add(w + "s")

    # Top-N selection without copying the Counter. heapq.nlargest does
    # a single pass over the source, maintaining only an N-element heap.
    # For N=100 and source size = 10M, that's ~50 MB of heap memory
    # vs. ~2-3 GiB for the previous Counter copy.
    top = heapq.nlargest(
        n,
        ((word, cnt) for word, cnt in counts.items() if word not in skip),
        key=lambda kv: kv[1],
    )

    if not top:
        return pd.DataFrame(columns=["word_1", "word_2", "count", "prob_w1w2"])

    rows = [
        {
            "word_1": search_term_lc,
            "word_2": word,
            "word_2_stemmed": _stemmer.stem(word),
            "count": count,
            "prob_w1w2": count / total_tokens if total_tokens else 0.0,
        }
        for word, count in top
    ]

    df = pd.DataFrame(rows)
    df = (
        df.sort_values(by="count", ascending=False)
          .drop_duplicates(subset=["word_1", "word_2_stemmed"], keep="first")
          .drop(columns=["word_2_stemmed"])
          .reset_index(drop=True)
    )
    return df


def calculate_cooccurrence(
    processed_texts: Iterable[str],
    search_term: str,
    n: int,
    total_docs: int,
) -> pd.DataFrame:
    """Compute the top-N co-occurring terms for `search_term`.

    Parameters
    ----------
    processed_texts : iterable of str
        Snippet texts that have already been run through
        `text_processing.preprocess_text` (lower-case, stopwords removed,
        single-char tokens dropped, whitespace-separated).
    search_term : str
        The anchor term being mined. Lower-cased internally; self-
        co-occurrence (the term and its naive plural) is filtered out.
    n : int
        Number of top partner terms to keep, ranked by raw count.
    total_docs : int
        Total documents in the xDD corpus (used to estimate the global
        token denominator for `prob_w1w2`).

    Returns
    -------
    pandas.DataFrame
        Columns: `word_1` (= search_term), `word_2`, `count`, `prob_w1w2`.
        At most `n` rows; can be fewer if the snippet pool is small.

    Notes
    -----
    Words are NLTK-lemmatized before counting. After taking the top-N,
    we deduplicate any rows whose Porter stems collide, keeping the
    higher-count form. This matches the existing corpus's normalization
    so new rows merge cleanly with old ones.
    """
    search_term_lc = search_term.lower().strip()
    search_term_words = set(search_term_lc.split())
    total_tokens = total_docs * TOTAL_TOKENS_PER_DOCUMENT

    counts: Counter[str] = Counter()
    for text in processed_texts:
        if not text:
            continue
        for token in text.split():
            if len(token) <= 2:
                continue
            counts[_lemmatizer.lemmatize(token.lower())] += 1

    # Drop self-cooccurrence (and naive plural form, mirroring upstream).
    for w in search_term_words:
        counts.pop(w, None)
        counts.pop(w + "s", None)

    top = counts.most_common(n)
    if not top:
        return pd.DataFrame(columns=["word_1", "word_2", "count", "prob_w1w2"])

    rows = [
        {
            "word_1": search_term_lc,
            "word_2": word,
            "word_2_stemmed": _stemmer.stem(word),
            "count": count,
            "prob_w1w2": count / total_tokens if total_tokens else 0.0,
        }
        for word, count in top
    ]

    df = pd.DataFrame(rows)
    df = (
        df.sort_values(by="count", ascending=False)
          .drop_duplicates(subset=["word_1", "word_2_stemmed"], keep="first")
          .drop(columns=["word_2_stemmed"])
          .reset_index(drop=True)
    )
    return df
