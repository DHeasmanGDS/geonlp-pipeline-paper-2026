#!/usr/bin/env python
"""Classify pending term_requests rows that don't yet have a term_class.

Runs as a CronJob (and also useful in foreground for one-shot backfill).
Picks up to `--batch-size` rows where `status='pending' AND
term_class IS NULL`, probes xDD for each term's snippet count, and
writes the assigned class back to the row.

Why a separate job (rather than classifying inline at insert time)?
  * The bulk-insert path (queue_term_request_bulk) doesn't want a
    per-row xDD round-trip — would slow user-facing UI submissions.
  * xDD outages would silently fail enqueue if classification were
    insert-time mandatory.
  * Re-classification (e.g., after a snapshot refresh) is a normal
    operation; the job pattern handles it naturally.

Race / fairness behavior:
  * The classifier respects requested_at order so the oldest pending
    rows get classified first — same fairness as the worker's claim
    order. Means new prioritized rows (bumped with old `requested_at`)
    get a class before they get claimed.
  * Idempotent: each tick processes only un-classified rows; a row
    classified on a prior tick is skipped.
  * If xDD is unreachable for a term (probe returns None), the row is
    left unclassified — the next tick will retry. We never persist a
    "best guess" class.

Exit codes:
  0  Tick completed (some rows classified, or queue was empty)
  1  Fatal error — DB unreachable, or xDD probe raised unexpected exception

Usage:
  python scripts/classify_pending_terms.py [--batch-size N] [--sleep S] [--once]

  --batch-size N   How many rows to classify per tick (default 100).
                   Each row = 1 xDD round-trip; tune to stay polite.
  --sleep S        Sleep between xDD probes in seconds (default 0.5).
                   Total tick budget ≈ batch_size * sleep + HTTP time.
  --once           Run a single pass and exit (default behavior; the
                   flag is explicit for use in foreground backfill).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.database import get_engine
from services.mining.term_classifier import classify_term


def fetch_unclassified_pending(engine, batch_size: int) -> list[tuple[int, str]]:
    """Return up to `batch_size` (id, term) pairs that need classifying.

    Uses the partial index `term_requests_unclassified_pending_idx`
    introduced in migration 0005 so the scan is essentially free even
    on a large queue.
    """
    sql = text("""
        SELECT id, term
        FROM term_requests
        WHERE status = 'pending'
          AND term_class IS NULL
        ORDER BY requested_at
        LIMIT :n
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"n": batch_size}).fetchall()
    return [(r.id, r.term) for r in rows]


def write_classification(engine, request_id: int, term_class: str, hits: int | None) -> None:
    """Persist the classifier's verdict to the row.

    Single row UPDATE; classification is idempotent so we don't need
    the SKIP LOCKED dance the worker uses.

    Special case for 'oversized': no worker pool claims oversized rows
    (small-medium pool excludes them; large pool also excludes them
    since they exceed SNAPSHOT_MAX_SNIPPETS_PER_TERM and would OOM
    even with pruning). So we mark them failed at classification time
    with a terminal error message — exactly what the worker's pre-flight
    check would have done if a worker had picked them up. The pre-flight
    check is retained as defense in depth for any oversized row that
    slips through (e.g., classification became stale after a snapshot
    change pushed a term over the threshold).
    """
    if term_class == "oversized":
        sql = text("""
            UPDATE term_requests
            SET term_class = :cls,
                hits_at_classify = :hits,
                classified_at = NOW(),
                status = 'failed',
                processed_at = NOW(),
                error_message = :err
            WHERE id = :id
              AND term_class IS NULL
        """)
        err = (
            f"auto-failed by classifier: xDD reports {hits:,} snippets, "
            f"exceeds SNAPSHOT_MAX_SNIPPETS_PER_TERM "
            f"(would OOM mid-mine even with pruning — class 'oversized')"
        )
        with engine.begin() as conn:
            conn.execute(sql, {"id": request_id, "cls": term_class,
                               "hits": hits, "err": err})
        return

    sql = text("""
        UPDATE term_requests
        SET term_class = :cls,
            hits_at_classify = :hits,
            classified_at = NOW()
        WHERE id = :id
          AND term_class IS NULL    -- still unclassified — don't overwrite a
                                    -- concurrent classification or a manual
                                    -- override.
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"id": request_id, "cls": term_class, "hits": hits})


def run_tick(engine, batch_size: int, sleep_between: float) -> dict:
    """One classification pass. Returns a counters dict for logging."""
    work = fetch_unclassified_pending(engine, batch_size)
    if not work:
        print("[classifier] no unclassified pending rows — nothing to do")
        return {"fetched": 0, "classified": 0, "unreachable": 0}

    print(f"[classifier] fetched {len(work)} unclassified pending row(s)")

    classified = 0
    unreachable = 0
    by_class: dict[str, int] = {}

    for i, (req_id, term) in enumerate(work, 1):
        try:
            result = classify_term(term)
        except Exception as e:
            # Don't poison the whole batch on one bad term. Log and skip.
            print(f"[classifier] '{term}' (id={req_id}) probe raised "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            unreachable += 1
            time.sleep(sleep_between)
            continue

        if not result.is_classified:
            # xDD unreachable for this term; leave the row alone, next
            # tick will retry.
            unreachable += 1
        else:
            write_classification(engine, req_id, result.term_class, result.hits)
            classified += 1
            by_class[result.term_class] = by_class.get(result.term_class, 0) + 1

        # Stay polite to xDD even on a healthy run.
        if i < len(work):
            time.sleep(sleep_between)

    summary = ", ".join(f"{k}={v}" for k, v in sorted(by_class.items()))
    print(f"[classifier] done: classified={classified} unreachable={unreachable} "
          f"({summary or 'none'})")
    return {
        "fetched": len(work),
        "classified": classified,
        "unreachable": unreachable,
        "by_class": by_class,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=100,
                        help="rows to classify per tick (default 100)")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="seconds between xDD probes (default 0.5)")
    parser.add_argument("--once", action="store_true",
                        help="(default) run a single pass and exit")
    args = parser.parse_args()
    # --once is the only mode for now; flag kept for explicitness and to
    # leave room for a future --watch mode if we want it.
    _ = args.once

    try:
        engine = get_engine()
        run_tick(engine, args.batch_size, args.sleep)
        return 0
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[classifier] FATAL: {type(e).__name__}: {e}\n{tb}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
