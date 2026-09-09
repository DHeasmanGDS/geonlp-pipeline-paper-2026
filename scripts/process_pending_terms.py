#!/usr/bin/env python
"""Process pending term_requests rows.

Picks the oldest pending request, mines xDD for snippets, computes
counts and pairwise co-occurrences, and inserts the rows into the
existing `term_counts` and `term_cooccurrence` tables. Then calls the
`update_all_statistics()` Postgres procedure to fill in
`mutual_information` and `entropy_w1w2` for the newly added rows.

Designed to be invoked by a Kubernetes CronJob every N minutes with
`concurrencyPolicy: Forbid`. Each run handles at most one term — long-tail
geological terms can take hours to mine, and that's fine.

Exit codes:
  0  Term processed successfully (or queue was empty — nothing to do)
  1  Failed; the term_requests row is marked status='failed' with the
     error message in error_message. Subsequent runs will skip it.

Usage:
  python scripts/process_pending_terms.py [--top-n N] [--dry-run]

  --top-n N    : how many partner terms to keep per anchor term
                 (default 100; this matches the existing corpus)
  --dry-run    : pull the next pending term and print what would happen,
                 without mining or writing anything.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

from collections import Counter

import pandas as pd
import requests
from sqlalchemy import text

# Make the repo root importable when run as a CronJob (no package install)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.database import (
    get_engine,
    insert_cooccurrence_via_copy,
    process_and_update_term_counts,
    remove_term,
)
from services.mining.cooccurrence import (
    accumulate_tokens,
    cooccurrence_from_counts,
    maybe_prune_counter,
)
from services.mining.text_processing import preprocess_text
from services.mining.xdd_harvester import (
    XddHarvestError,
    get_total_hits,
    iter_snippets,
)
from services.mining_config import (
    MAX_CONCURRENT_LARGE,
    MAX_CONCURRENT_MINERS,
    MAX_CONCURRENT_SMALL_MEDIUM,
    SNAPSHOT_MAX_SNIPPETS_PER_TERM,
    SNAPSHOT_PRUNE_CHECK_INTERVAL,
    SNAPSHOT_PRUNE_KEEP_MIN,
    SNAPSHOT_PRUNE_TRIGGER_SIZE,
    SNAPSHOT_TOKENS_PER_DOCUMENT,
    SNAPSHOT_TOTAL_DOCS,
    TERM_CLASSES,
    xdd_snapshot_params,
)


# Default top-N partners per anchor term — matches the volume in the
# existing corpus (the MSc notebooks used 100).
DEFAULT_TOP_N = 100


class RetryableMiningError(Exception):
    """A mining failure that is expected to succeed on a later attempt.

    Raised for transient xDD problems that surface mid-stream (network
    blips, DNS hiccups, rate limiting, 5xx) — the kind of thing a router
    reboot or a brief upstream outage causes. Distinct from *terminal*
    failures (oversized terms, zero coverage, schema/DB errors), which
    keep raising RuntimeError and are marked status='failed' for good.

    The worker catches this in main() and resets the request to
    'pending' so the next cron tick re-mines it, up to
    MAX_RETRYABLE_ATTEMPTS. Before this existed, a transient mid-stream
    failure marked the row 'failed' permanently even though its own
    message said "(retryable ...)", so every power/DNS blip silently
    sidelined whatever terms were mid-mine until someone re-queued them
    by hand.
    """


# How many times a request may be mined before a *retryable* failure is
# treated as terminal. Each retry re-mines the term from scratch, so keep
# this small: a deep mid-stream blip on a 20M-snippet term costs a full
# re-mine. The xDD liveness check at the top of main() means a re-queued
# term is not re-claimed until xDD is reachable again, so retries wait
# out an outage rather than burning cron ticks during it.
MAX_RETRYABLE_ATTEMPTS = 3


def implied_total_docs(engine) -> int | None:
    """Back-derive total_docs from existing term_counts for verification.

    Returns None if the table is empty. Useful for confirming that the
    pinned SNAPSHOT_TOTAL_DOCS in services/mining_config.py matches what
    the original corpus was actually built against — if the back-derived
    value disagrees with the pinned constant, future mines will produce
    inconsistent probabilities relative to existing rows.

    NOT called in the normal mining path anymore. Use the pinned
    SNAPSHOT_TOTAL_DOCS constant directly so that mining is
    deterministic and reproducible.
    """
    sql = text("""
        SELECT count, probability
        FROM term_counts
        WHERE probability IS NOT NULL AND probability > 0
        ORDER BY count DESC
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    if not row:
        return None
    count, probability = row
    return int(round(count / probability / SNAPSHOT_TOKENS_PER_DOCUMENT))


# Wall-clock cap for a single mining run. Beyond this, the row is
# considered a zombie (pod died mid-mining without marking its
# request done/failed). Matches the CronJob's activeDeadlineSeconds
# of 604800s = 7d, with a small grace period.
ZOMBIE_THRESHOLD_HOURS = 24 * 7 + 1  # 169h = 7d + 1h grace


def reclaim_zombies(engine) -> int:
    """Reset any rows stuck in 'running' beyond ZOMBIE_THRESHOLD_HOURS
    back to 'pending'. Returns the number of rows touched.

    Called at the top of each cron-driven claim. The typical cause of
    zombies is OOM-kill or pod eviction: the worker dies before its
    except handler can mark the request failed, so the row sits in
    'running' indefinitely and no future miner picks it up.

    Safe to run on every cron tick — the WHERE clause uses the
    partial index `term_requests_running_started_idx` so the scan is
    essentially free.
    """
    sql = text("""
        UPDATE term_requests
        SET status = 'pending',
            started_at = NULL
        WHERE status = 'running'
          AND started_at IS NOT NULL
          AND started_at < NOW() - make_interval(hours => :hours)
    """)
    with engine.begin() as conn:
        result = conn.execute(sql, {"hours": ZOMBIE_THRESHOLD_HOURS})
        return result.rowcount or 0


def claim_next_pending(engine, allowed_classes: list[str] | None = None):
    """Atomically pick + mark the oldest pending request as 'running'.

    Uses SELECT … FOR UPDATE SKIP LOCKED so two concurrent workers can
    coexist (the CronJob has Forbid concurrency, but defense in depth is
    cheap). Returns the row's `id` and `term`, or (None, None) if the
    queue is empty.

    Also stamps `started_at = NOW()` so the janitor (reclaim_zombies)
    can detect pods that die mid-mining.

    Pool routing: when `allowed_classes` is provided (e.g.
    ['small','medium'] for the small-medium pool, ['large'] for the
    large pool), only rows whose `term_class` matches are eligible.
    Rows with `term_class IS NULL` are NOT claimed by a scoped pool —
    they wait for the classifier CronJob to tag them first. (NULL rows
    used to be claimable by any pool as a rollout fallback, but that let
    an unclassified row mined by one pool count toward EVERY pool's cap
    and starve the others — e.g. small-pool NULL mines pinning the large
    pool at "full". The classifier now runs often enough to tag rows
    promptly, so each pool sticks to its own class.)

    When `allowed_classes` is None or empty, ALL classes (and NULL)
    are eligible — the old behavior, retained so the worker remains
    usable in single-pool mode.
    """
    reclaimed = reclaim_zombies(engine)
    if reclaimed > 0:
        print(f"[worker] janitor: reset {reclaimed} zombie row(s) back to pending")

    # Build the WHERE clause dynamically so the prepared statement
    # parameter list stays a list of strings even when allowed_classes
    # is empty/None.
    if allowed_classes:
        pick = text("""
            SELECT id, term, term_class
            FROM term_requests
            WHERE status = 'pending'
              AND term_class = ANY(:classes)
            ORDER BY requested_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        params = {"classes": list(allowed_classes)}
    else:
        pick = text("""
            SELECT id, term, term_class
            FROM term_requests
            WHERE status = 'pending'
            ORDER BY requested_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        params = {}

    mark = text("""
        UPDATE term_requests
        SET status = 'running',
            started_at = NOW()
        WHERE id = :id
    """)
    with engine.begin() as conn:
        row = conn.execute(pick, params).fetchone()
        if not row:
            return None, None
        conn.execute(mark, {"id": row.id})
        return row.id, row.term


def mark_done(engine, request_id: int) -> None:
    sql = text("""
        UPDATE term_requests
        SET status = 'done',
            processed_at = NOW(),
            error_message = NULL
        WHERE id = :id
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"id": request_id})


def mark_failed(engine, request_id: int, error: str) -> None:
    sql = text("""
        UPDATE term_requests
        SET status = 'failed',
            processed_at = NOW(),
            error_message = :err
        WHERE id = :id
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"id": request_id, "err": error[:8000]})


def _retry_attempt_so_far(engine, request_id: int) -> int:
    """How many times this request has already failed retryably.

    Parsed from the "[retry N/M]" prefix that requeue_for_retry() writes
    into error_message. Returns 0 if there is no such marker (the row has
    never failed retryably) or if the read fails — defaulting to 0 keeps
    the safer behavior (retry rather than give up) when the DB is flaky.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT error_message FROM term_requests WHERE id = :id"),
                {"id": request_id},
            ).fetchone()
    except Exception:
        return 0
    msg = row[0] if row else None
    if msg and msg.startswith("[retry "):
        try:
            return int(msg[len("[retry "):msg.index("]")].split("/")[0])
        except (ValueError, IndexError):
            return 0
    return 0


def requeue_for_retry(engine, request_id: int, attempt: int, error: str) -> None:
    """Reset a request to 'pending' after a retryable failure.

    Records the attempt count in error_message as a "[retry N/M]" prefix
    so the next run can tell how many times this term has failed without
    a schema change. The marker is cleared by mark_done() on eventual
    success. started_at is nulled so the row looks like any other pending
    row (and the zombie reaper ignores it).
    """
    note = f"[retry {attempt}/{MAX_RETRYABLE_ATTEMPTS}] {error}"
    sql = text("""
        UPDATE term_requests
        SET status = 'pending',
            started_at = NULL,
            error_message = :msg
        WHERE id = :id
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"id": request_id, "msg": note[:8000]})


def already_processed(engine, term: str) -> bool:
    """If the term is already in `processed_terms`, mining was completed
    in an earlier run (or out-of-band). Skip the work and just close the
    request.
    """
    sql = text("SELECT 1 FROM processed_terms WHERE term = :t LIMIT 1")
    with engine.connect() as conn:
        return conn.execute(sql, {"t": term.lower()}).fetchone() is not None


def mark_processed(engine, term: str) -> None:
    sql = text("""
        INSERT INTO processed_terms (term)
        VALUES (:t)
        ON CONFLICT (term) DO NOTHING
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"t": term.lower()})


def update_all_statistics(engine) -> None:
    """Full-table MI/entropy recompute. ~3h on a 9GB cooccurrence table.

    Kept for one-off manual use; the worker no longer calls this. The
    daily `geonlp-stats-refresh` CronJob runs it as a defensive sweep,
    but per-term updates from `update_all_statistics_for_term()` should
    keep the table consistent in the normal case.
    """
    with engine.begin() as conn:
        conn.execute(text("CALL update_all_statistics();"))


def update_all_statistics_for_term(engine, term: str) -> None:
    """Incremental MI/entropy recompute scoped to one term.

    Updates:
      - rows where word_1 = term (just-mined)
      - rows where word_2 = term (existing partners that referenced this
        term before it was in `term_counts` and so had NULL MI)
      - the term's own row in `term_counts.entropy`

    Defined in `db/migrations/9999_update_all_statistics_for_term.sql`.
    Completes in milliseconds — math is per-row local with no
    cross-row aggregation. Replaces the multi-hour full-table recompute
    that the worker used to call after each term.
    """
    with engine.begin() as conn:
        conn.execute(
            text("CALL update_all_statistics_for_term(:t)"),
            {"t": term},
        )


def process_term(engine, term: str, top_n: int, *, dry_run: bool = False,
                 skip_preflight: bool = False) -> dict:
    """Run the full mining pipeline for one term.

    Returns a dict of counters useful for logging. Raises on
    unrecoverable failure (caller turns it into a 'failed' row).

    Memory model: streams xDD snippets one at a time through
    preprocessing into a Counter of lemmatized token frequencies. Never
    materializes the full snippet list. Peak memory is bounded by
    `O(unique_tokens)` rather than `O(snippets * avg_text_size)` —
    important for popular terms like 'mineral' (480k+ snippets) which
    OOM-killed the previous materializing implementation.
    """
    term_lc = term.strip().lower()
    if not term_lc:
        raise ValueError("empty term")

    print(f"[worker] mining '{term_lc}' (streaming)")

    # Pre-flight check: probe xDD for the term's total snippet count
    # before claiming and start mining. Terms with snippet counts above
    # SNAPSHOT_MAX_SNIPPETS_PER_TERM are too common to mine reliably —
    # the streaming Counter's unique-token vocabulary will exceed pod
    # memory limits and OOMKill mid-mine, creating a zombie row.
    #
    # If xDD is unreachable for the probe (returns None), proceed with
    # mining anyway — the harvester's own retry logic will kick in and
    # we don't want to silently fail terms during xDD outages.
    harvest_params = {"clean": "true", **xdd_snapshot_params()}
    if skip_preflight:
        # Deliberate big-term mine in a larger-memory pod (see
        # scripts/mine_one_term.py). Bypass the size gate entirely.
        print(f"[worker] '{term_lc}': pre-flight SKIPPED (skip_preflight=True) — "
              f"mining regardless of size; relies on the running pod's memory budget")
    else:
        total_hits = get_total_hits(term_lc, extra_params=harvest_params)
        if total_hits is not None and total_hits > SNAPSHOT_MAX_SNIPPETS_PER_TERM:
            raise RuntimeError(
                f"xDD reports {total_hits:,} snippets for '{term_lc}', exceeds "
                f"SNAPSHOT_MAX_SNIPPETS_PER_TERM ({SNAPSHOT_MAX_SNIPPETS_PER_TERM:,}) "
                f"(terminal — too common to mine reliably under current memory budget; "
                f"would OOM mid-mine and orphan the row)"
            )
        if total_hits is not None:
            print(f"[worker] '{term_lc}': pre-flight reports {total_hits:,} snippets "
                  f"(threshold {SNAPSHOT_MAX_SNIPPETS_PER_TERM:,}); proceeding")

    # 1+2 streaming: pull each xDD snippet, preprocess, lemmatize-and-
    # count. Memory peak is the Counter, not the snippet list.
    #
    # XddHarvestError vs zero-snippets: a clean exit with n_snippets == 0
    # means xDD genuinely has nothing for this term. Catching
    # XddHarvestError separately means we got rate-limited / network-
    # errored — the term is potentially retryable, NOT a terminal
    # "no coverage" verdict.
    counts: Counter = Counter()
    n_snippets = 0
    # `harvest_params` already declared above for the pre-flight probe;
    # reused here for the full streaming mine to keep snapshot params
    # consistent across both requests.
    try:
        for snippet in iter_snippets(term_lc, extra_params=harvest_params):
            n_snippets += 1
            text_clean = preprocess_text(snippet)
            accumulate_tokens(text_clean, counts)

            # Periodic in-stream pruning to bound memory on mega-frequency
            # terms. Without this, the Counter for very common words
            # ('environment', 'ratio', 'system') can exceed the 1Gi pod
            # memory limit during streaming and OOM-kill the worker before
            # the mine completes. The pruning drops entries appearing
            # fewer than SNAPSHOT_PRUNE_KEEP_MIN times, which by
            # construction have near-zero PMI and cannot influence the
            # top-N partner ranking. See §5 of the methodology paper for
            # the trade-off discussion.
            if n_snippets % SNAPSHOT_PRUNE_CHECK_INTERVAL == 0:
                maybe_prune_counter(
                    counts,
                    n_snippets,
                    trigger_size=SNAPSHOT_PRUNE_TRIGGER_SIZE,
                    keep_min=SNAPSHOT_PRUNE_KEEP_MIN,
                )
    except XddHarvestError as e:
        raise RetryableMiningError(
            f"xDD harvest failed for '{term_lc}' (retryable — likely "
            f"rate-limited or transient outage): {e}"
        )

    if n_snippets == 0:
        raise RuntimeError(
            f"xDD returned zero snippets for '{term_lc}' "
            f"(terminal — xDD has no coverage for this term)"
        )

    print(f"[worker] '{term_lc}': {n_snippets} snippets streamed, "
          f"{len(counts):,} unique lemmas counted")

    if dry_run:
        print(f"[worker] DRY RUN — not writing to DB. Would compute top-{top_n} cooccurrences "
              f"and insert into term_counts + term_cooccurrence.")
        return {"term": term_lc, "snippets": n_snippets, "unique_tokens": len(counts), "dry_run": True}

    # 3. Compute pairwise co-occurrence from the running counter.
    # total_docs is pinned to the snapshot (NOT back-derived from
    # existing rows) so probabilities stay deterministic and comparable
    # across re-mines / re-runs.
    total_docs = SNAPSHOT_TOTAL_DOCS
    cooc = cooccurrence_from_counts(
        counts=counts,
        search_term=term_lc,
        n=top_n,
        total_docs=total_docs,
    )
    print(f"[worker] '{term_lc}': {len(cooc)} partner terms")

    # We need a lightweight df for process_and_update_term_counts which
    # only reads len() — pass a thin shim DataFrame instead of holding
    # all snippets in memory.
    df_count_shim = pd.DataFrame({"_": [None] * n_snippets})

    # 4. Persist counts → mark processed → insert cooccurrence pairs.
    #
    # IMPORTANT ORDERING: term_cooccurrence has a foreign key
    # (fk_word_1_processed_terms) that requires the term to exist in
    # `processed_terms` before any cooccurrence row referencing it can
    # be inserted. So mark_processed MUST come before the cooccurrence
    # insert.
    #
    # If anything fails after term_counts.write, we use remove_term to
    # roll back to a clean state so a retry can start fresh.
    process_and_update_term_counts(df_count_shim, term_lc, total_docs, engine)
    try:
        mark_processed(engine, term_lc)
        if not cooc.empty:
            insert_cooccurrence_via_copy(engine, cooc)
    except Exception:
        print(f"[worker] '{term_lc}': insert failed; cleaning up partial state",
              file=sys.stderr)
        try:
            remove_term(engine, term_lc)
        except Exception as cleanup_err:
            # Best-effort — surface the cleanup failure but raise the
            # original exception below.
            print(f"[worker] cleanup also failed: {cleanup_err}", file=sys.stderr)
        raise

    # 5. Per-term MI/entropy recompute. Cheap (milliseconds) and only
    # touches rows that just changed; freshly mined terms have full
    # metrics populated immediately. The daily `geonlp-stats-refresh`
    # CronJob still runs as a defensive sweep but should be a no-op
    # in steady state.
    #
    # Resilient: if the proc doesn't exist yet (migration
    # 9999_update_all_statistics_for_term.sql not applied), warn but
    # don't fail the worker — the data is correct, the daily refresh
    # will populate the derived columns.
    print(f"[worker] '{term_lc}': running update_all_statistics_for_term()")
    try:
        update_all_statistics_for_term(engine, term_lc)
    except Exception as e:
        print(
            f"[worker] WARN: update_all_statistics_for_term('{term_lc}') failed: "
            f"{type(e).__name__}: {e}\n"
            f"[worker] data is committed; daily geonlp-stats-refresh will catch this.",
            file=sys.stderr,
        )

    return {
        "term": term_lc,
        "snippets": n_snippets,
        "unique_tokens": len(counts),
        "partners": len(cooc),
        "total_docs_used": total_docs,
    }


# The per-pool concurrent-miner caps (MAX_CONCURRENT_SMALL_MEDIUM,
# MAX_CONCURRENT_LARGE, MAX_CONCURRENT_MINERS) are defined in
# services/mining_config.py and imported at the top of this module, so
# the worker's enforced cap and the cap shown on the Request-a-term page
# can never drift apart. See that file for the NUC sizing rationale.


def count_running_miners(engine, allowed_classes: list[str] | None = None) -> int:
    """Count term_requests rows currently in 'running' state, optionally
    scoped to a class set.

    Used as a soft cap on concurrent miners. Note this also counts
    zombie rows (pods that died without marking their row done/failed)
    — if the count is artificially high because of zombies, the janitor
    will catch them and reset to pending. Until then, new miners will
    skip ticks until the count goes back below the cap.

    Class filter mirrors claim_next_pending: a scoped count includes
    ONLY the pool's own class. NULL (unclassified) rows are not counted —
    a scoped pool no longer claims them, so counting them would inflate
    the cap and let one pool's unclassified work stall another.
    """
    if allowed_classes:
        sql = text("""
            SELECT COUNT(*)
            FROM term_requests
            WHERE status = 'running'
              AND term_class = ANY(:classes)
        """)
        params = {"classes": list(allowed_classes)}
    else:
        sql = text("SELECT COUNT(*) FROM term_requests WHERE status = 'running'")
        params = {}
    with engine.connect() as conn:
        return int(conn.execute(sql, params).scalar() or 0)


def xdd_is_reachable(timeout: float = 8.0) -> bool:
    """Liveness probe against xDD's snippets endpoint with a real query.

    Returns False on any of:
      - network error / timeout / connection refused
      - HTTP 5xx
      - HTTP 200 but response body lacks the `success` block (xDD's
        HTTP layer can be up while Elasticsearch is in
        `cluster_block_exception` during partial recovery — observed
        2026-05-16. The API root returns 200 in that state but
        snippet queries return only an `error` payload.)

    The cron-scheduled worker calls this BEFORE claiming a row — when
    xDD is down or half-up, bailing in seconds saves ~20 min of retry
    burn per cron tick AND avoids marking real terms as "zero
    coverage" when the backend index is just rebuilding.
    """
    try:
        r = requests.get(
            "https://xdd.wisc.edu/api/snippets",
            params={"term": "granite", "per_page": "1"},
            timeout=timeout,
        )
        if r.status_code >= 500:
            return False
        body = r.json()
    except (requests.RequestException, ValueError):
        return False
    # 'success' key present === Elasticsearch is serving queries.
    return "success" in body


def _parse_classes_arg(raw: str | None) -> list[str] | None:
    """Validate and normalize the --class argument.

    Accepts a comma-separated list like "small,medium". Returns the
    list (preserving order), or None if no classes were given (pool-
    unaware mode — claim from any class). Raises SystemExit on an
    unknown class name so the worker fails fast in CI / kubectl logs.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    bad = [p for p in parts if p not in TERM_CLASSES]
    if bad:
        sys.stderr.write(
            f"[worker] FATAL: unknown class name(s) in --class={raw}: {bad}. "
            f"Allowed: {list(TERM_CLASSES)}\n"
        )
        raise SystemExit(2)
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                        help=f"top partner terms to keep (default {DEFAULT_TOP_N})")
    parser.add_argument("--dry-run", action="store_true",
                        help="claim a pending row and print what would happen, without writing")
    parser.add_argument("--skip-xdd-check", action="store_true",
                        help="skip the upfront xDD liveness check (useful for testing)")
    parser.add_argument("--class", dest="classes", default=None,
                        help="comma-separated list of term classes this worker is allowed "
                             "to claim (e.g. 'small,medium' or 'large'). Omit for any-class "
                             "behavior. Unknown class names fail fast.")
    parser.add_argument("--max-concurrent", type=int, default=None,
                        help="override the per-pool concurrent-miner cap. Defaults: "
                             f"{MAX_CONCURRENT_SMALL_MEDIUM} for small-medium pool, "
                             f"{MAX_CONCURRENT_LARGE} for large pool, "
                             f"{MAX_CONCURRENT_MINERS} for unscoped runs.")
    args = parser.parse_args()

    allowed_classes = _parse_classes_arg(args.classes)

    # Resolve the concurrency cap based on which pool we're acting as.
    if args.max_concurrent is not None:
        cap = args.max_concurrent
    elif allowed_classes is None:
        cap = MAX_CONCURRENT_MINERS
    elif set(allowed_classes) == {"large"}:
        cap = MAX_CONCURRENT_LARGE
    else:
        # 'small', 'medium', or any combination of small/medium → use
        # the small-medium pool cap. Mixed sets that include 'large'
        # would be unusual; fall back to the conservative large cap.
        cap = (MAX_CONCURRENT_LARGE
               if "large" in allowed_classes
               else MAX_CONCURRENT_SMALL_MEDIUM)

    pool_label = (",".join(allowed_classes) if allowed_classes else "any")

    # Circuit breaker: bail before claiming if xDD looks dead.
    # Saves ~20 min of retry burn per cron tick during outages.
    if not args.skip_xdd_check and not xdd_is_reachable():
        print(f"[worker] [{pool_label}] xDD appears unreachable — skipping this cron tick "
              "(will retry next tick)")
        return 0

    engine = get_engine()

    # Concurrency cap: with Allow + frequent cron schedule, pods can
    # accumulate during long mines. Skip if we're already at the cap.
    # Counts DB rows in 'running' state scoped to allowed_classes (+
    # NULL); zombie rows count too (caller can rely on the hourly
    # janitor to clear those).
    running = count_running_miners(engine, allowed_classes=allowed_classes)
    if running >= cap:
        print(f"[worker] [{pool_label}] {running} miners already running "
              f"(cap={cap}) — skipping this cron tick")
        return 0

    request_id, term = claim_next_pending(engine, allowed_classes=allowed_classes)
    if request_id is None:
        print(f"[worker] [{pool_label}] queue is empty — nothing to do")
        return 0

    print(f"[worker] claimed request id={request_id} term='{term}'")
    started = time.time()

    try:
        if already_processed(engine, term):
            print(f"[worker] '{term}' already in processed_terms — closing request without remining")
            mark_done(engine, request_id)
            return 0

        result = process_term(engine, term, args.top_n, dry_run=args.dry_run)

        if args.dry_run:
            # Don't change state on dry-run; just print and exit.
            # Reset back to pending so a real run can claim it.
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE term_requests SET status = 'pending' WHERE id = :id"),
                    {"id": request_id},
                )
            print(f"[worker] DRY RUN done; reverted to pending. {result}")
            return 0

        mark_done(engine, request_id)
        elapsed = time.time() - started
        print(f"[worker] '{term}' DONE in {elapsed/60:.1f} min: {result}")
        return 0

    except RetryableMiningError as e:
        # Transient xDD failure (network / DNS / rate-limit / 5xx). Put
        # the term back to 'pending' so a later tick re-mines it, up to
        # MAX_RETRYABLE_ATTEMPTS, instead of marking it failed for good.
        elapsed = time.time() - started
        attempt = _retry_attempt_so_far(engine, request_id) + 1
        if attempt < MAX_RETRYABLE_ATTEMPTS:
            try:
                requeue_for_retry(engine, request_id, attempt,
                                  f"{type(e).__name__}: {e}")
            except Exception as inner:
                print(f"[worker] '{term}': also failed to requeue: {inner}",
                      file=sys.stderr)
                return 1
            print(f"[worker] '{term}' transient failure after {elapsed/60:.1f} min "
                  f"(attempt {attempt}/{MAX_RETRYABLE_ATTEMPTS}) — requeued to pending: {e}",
                  file=sys.stderr)
            return 0
        # Out of retries: stop re-mining and mark it failed for good so
        # it does not loop forever on a term that always dies mid-stream.
        print(f"[worker] '{term}' still failing after {attempt} attempts "
              f"({elapsed/60:.1f} min) — marking failed: {e}", file=sys.stderr)
        try:
            mark_failed(engine, request_id,
                        f"exhausted {MAX_RETRYABLE_ATTEMPTS} retryable attempts; "
                        f"last error: {type(e).__name__}: {e}")
        except Exception as inner:
            print(f"[worker] also failed to mark request failed: {inner}", file=sys.stderr)
        return 1

    except Exception as e:
        elapsed = time.time() - started
        tb = traceback.format_exc()
        print(f"[worker] '{term}' FAILED after {elapsed/60:.1f} min: {e}\n{tb}",
              file=sys.stderr)
        try:
            mark_failed(engine, request_id, f"{type(e).__name__}: {e}")
        except Exception as inner:
            print(f"[worker] also failed to mark request failed: {inner}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
