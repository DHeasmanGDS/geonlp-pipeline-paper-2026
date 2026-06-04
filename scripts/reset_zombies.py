#!/usr/bin/env python
"""Standalone zombie reaper for term_requests.

Resets any term_requests row stuck in `status='running'` with
`started_at < NOW() - threshold_hours` back to `pending` so the next
miner can pick it up.

Why this exists as a separate script instead of being part of the
miner: the miner-CronJob has `concurrencyPolicy: Forbid`, so its own
janitor (`scripts/process_pending_terms.py::reclaim_zombies`) can't
run while a long mine is in progress. Popular terms like `water` and
`mineral` can mine for 12-40+ hours — long enough that other rows
stuck in `running` accumulate without ever being reclaimed.

This script runs from its own CronJob without `Forbid`, so it
reliably fires on schedule regardless of what the miner is doing.

Exit codes:
  0  finished cleanly (with 0 or N rows reset)
  1  unhandled error

Usage:
  python scripts/reset_zombies.py [--hours N]
  --hours N   override the default zombie age threshold (default 25)
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.database import get_engine


# Matches the CronJob's activeDeadlineSeconds (48) with a
# 1-hour grace period.
DEFAULT_HOURS = 48 + 1


def reclaim(engine, hours: int) -> int:
    sql = text("""
        UPDATE term_requests
        SET status = 'pending',
            started_at = NULL
        WHERE status = 'running'
          AND started_at IS NOT NULL
          AND started_at < NOW() - make_interval(hours => :h)
    """)
    with engine.begin() as conn:
        result = conn.execute(sql, {"h": hours})
        return result.rowcount or 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS,
                        help=f"zombie age threshold (default {DEFAULT_HOURS})")
    args = parser.parse_args()

    engine = get_engine()
    try:
        n = reclaim(engine, args.hours)
    except Exception as e:
        print(f"[janitor] ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if n > 0:
        print(f"[janitor] reset {n} zombie row(s) older than {args.hours}h back to pending")
    else:
        print(f"[janitor] no zombies older than {args.hours}h — nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
