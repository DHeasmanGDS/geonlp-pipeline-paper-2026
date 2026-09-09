#!/usr/bin/env python
"""Mine ONE named term out of band, bypassing pool routing and the
SNAPSHOT_MAX_SNIPPETS_PER_TERM pre-flight gate.

For deliberately mining an important term that the classifier would
otherwise decline as 'oversized' (e.g. 'carbonate', ~2.07M docs). Run in
a dedicated, larger-memory one-off Job (see k8s/mine-carbonate-job.yaml)
so it has the headroom the standard 1Gi/4Gi pools don't.

It reuses process_term() exactly (with skip_preflight=True), so the
streaming, in-stream pruning, cooccurrence computation, FK-safe insert
ordering, and per-term stats refresh are all identical to the normal
worker — only the size gate is skipped.

Usage:
  python scripts/mine_one_term.py --term carbonate [--top-n 100]
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

# Make both the repo root and this scripts/ dir importable whether run
# as a module or a bare script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text

from services.database import get_engine
import process_pending_terms as ppt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", required=True, help="exact term to mine")
    parser.add_argument("--top-n", type=int, default=ppt.DEFAULT_TOP_N,
                        help=f"top partner terms to keep (default {ppt.DEFAULT_TOP_N})")
    args = parser.parse_args()

    term = args.term.strip().lower()
    if not term:
        print("[mine-one] empty term", file=sys.stderr)
        return 2

    engine = get_engine()

    if ppt.already_processed(engine, term):
        print(f"[mine-one] '{term}' already in processed_terms — nothing to do")
        return 0

    # Reserve the request row (if one exists) so the pools don't also
    # grab it while this dedicated run is in flight.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE term_requests SET status='running', started_at=NOW() WHERE term=:t"),
            {"t": term},
        )

    try:
        result = ppt.process_term(engine, term, args.top_n, skip_preflight=True)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[mine-one] '{term}' FAILED: {e}\n{tb}", file=sys.stderr)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE term_requests SET status='failed', processed_at=NOW(), "
                         "error_message=:err WHERE term=:t"),
                    {"t": term, "err": f"dedicated mine failed: {type(e).__name__}: {e}"[:8000]},
                )
        except Exception as inner:
            print(f"[mine-one] also failed to mark request failed: {inner}", file=sys.stderr)
        return 1

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE term_requests SET status='done', processed_at=NOW(), "
                 "term_class='large', error_message=NULL WHERE term=:t"),
            {"t": term},
        )
    print(f"[mine-one] '{term}' DONE: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
