#!/usr/bin/env python
"""Recompute MI/entropy across all term_cooccurrence rows.

Calls the Postgres procedure `update_all_statistics()` once with a
generous statement timeout. Designed to be invoked by a Kubernetes
CronJob (`k8s/geonlp-stats-cronjob.yaml`) on a daily schedule.

Why decoupled from mining: the proc scans the entire 9GB cooccurrence
table on every invocation and takes minutes to complete. Calling it
after every term mining made each mining job mostly wait on the DB
instead of actually harvesting. Splitting it out means:

- Mining workers complete in seconds (the harvest + token math is fast)
- Stats refresh runs at a known time, hammering the DB once a day
  instead of 2-6 times per hour at unpredictable moments
- The current corpus's MI/entropy stays correct for everything *already*
  computed; only freshly mined rows have NULL until the next refresh

Future work (ARCHITECTURE_REVIEW.md item 8): rewrite the proc to take a
term name argument and only update rows for that term, then call the
incremental version from the worker per-term and drop this CronJob
entirely. Blocked on first capturing the proc source into version
control.

Usage:
  python scripts/refresh_statistics.py                # default 6h timeout
  python scripts/refresh_statistics.py --timeout 1h   # custom

Exits 0 on success, 1 on timeout/error.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Make the repo root importable when run as a CronJob (no package install)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from services.database import get_engine


def parse_timeout(s: str) -> str:
    """Accept '6h', '90m', '300s', or a bare integer (seconds) and return
    a Postgres-formatted statement_timeout string in milliseconds.
    """
    s = s.strip().lower()
    if s.endswith("h"):
        ms = int(float(s[:-1]) * 3_600_000)
    elif s.endswith("m"):
        ms = int(float(s[:-1]) * 60_000)
    elif s.endswith("s"):
        ms = int(float(s[:-1]) * 1_000)
    else:
        ms = int(s) * 1_000
    return f"{ms}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout",
        default="6h",
        help="Postgres statement_timeout (e.g. '6h', '90m', '300s'). Default 6h.",
    )
    args = parser.parse_args()

    timeout_ms = parse_timeout(args.timeout)
    print(f"[stats] starting update_all_statistics() with statement_timeout={timeout_ms}ms")

    started = time.time()
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(f"SET statement_timeout = {timeout_ms}"))
            conn.execute(text("CALL update_all_statistics();"))
    except Exception as e:
        elapsed = time.time() - started
        print(f"[stats] FAILED after {elapsed/60:.1f} min: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    elapsed = time.time() - started
    print(f"[stats] update_all_statistics() complete in {elapsed/60:.2f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
