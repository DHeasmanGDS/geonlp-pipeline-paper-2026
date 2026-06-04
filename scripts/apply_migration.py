#!/usr/bin/env python
"""Apply a SQL migration file to the configured database.

Avoids needing psql installed locally or SSH into the NAS — uses the
same SQLAlchemy connection pool the app already uses, so credentials
come from `services/.env` (locally) or the `geonlp-env` Kubernetes
Secret (when run as a Job in the cluster).

The migrations under `db/migrations/` are written to be idempotent
(every ALTER uses IF NOT EXISTS / DROP IF EXISTS), so re-running this
script is safe.

Usage:
    python scripts/apply_migration.py db/migrations/0001_term_requests_status.sql

    # From inside the cluster as a one-off Job:
    kubectl run apply-mig --rm -it --restart=Never \\
        --image=geonlp-portal:latest \\
        --image-pull-policy=Never \\
        --overrides='{"spec":{"containers":[{"name":"apply-mig","image":"geonlp-portal:latest","imagePullPolicy":"Never","command":["python","scripts/apply_migration.py","db/migrations/0001_term_requests_status.sql"],"envFrom":[{"secretRef":{"name":"geonlp-env"}}]}]}}'
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the repo root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from services.database import get_engine


def apply_sql_file(engine, sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    print(f"[migrate] applying {sql_path} ({len(sql)} chars)")
    with engine.begin() as conn:
        # `text()` accepts statements with semicolons; psycopg2 drives the
        # multi-statement parsing. The whole file runs in one transaction
        # so partial failures roll back cleanly.
        conn.execute(text(sql))
    print("[migrate] applied successfully")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sql_file", type=Path, help="Path to the .sql file to apply")
    args = parser.parse_args()

    if not args.sql_file.exists():
        print(f"ERROR: {args.sql_file} not found", file=sys.stderr)
        return 1

    engine = get_engine()
    try:
        apply_sql_file(engine, args.sql_file)
    except Exception as e:
        print(f"ERROR: migration failed — {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
