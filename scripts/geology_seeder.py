#!/usr/bin/env python
"""Geology term seeder — the deliberate counterpart to the accidental
auto-queue crawler. Keeps the mining queue topped up with GEOLOGY terms
so geology coverage grows on purpose instead of drifting toward whatever
a web crawler happens to view.

Two sources per run:
  1. Lexicon breadth: queue net-new single-word geology terms from
     data/geo_lexicon.txt (services.geo_lexicon) that aren't already
     requested or mined.
  2. Graph expansion (coverage): walk the co-occurrence graph out from
     already-mined geology terms and queue their unmined partners that
     also look geological (co-occur with >= K distinct geology seeds, or
     are themselves in the lexicon). This is the geology-scoped version
     of the crawler's link-following, and it's what actually drives
     coverage over geology papers.

The batch is capped per run so it tops up steadily rather than flooding,
and it only ever inserts net-new terms (deduped against term_requests +
processed_terms), so it self-limits when there's nothing new to add.

Usage:
  python scripts/geology_seeder.py [--batch N] [--min-geo-neighbors K]
                                    [--seed-cap C] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from services.database import get_engine
from services.geo_lexicon import geo_terms


def existing_terms(engine) -> set:
    """Lowercased terms already requested or mined — skip these."""
    seen = set()
    with engine.connect() as conn:
        for r in conn.execute(text("SELECT lower(term) FROM term_requests")):
            if r[0]:
                seen.add(r[0])
        for r in conn.execute(text("SELECT lower(term) FROM processed_terms")):
            if r[0]:
                seen.add(r[0])
    return seen


def mined_geo_seeds(engine, lex: frozenset, cap: int) -> list:
    """Up to `cap` already-mined terms that are in the lexicon — the
    geology frontier to expand the co-occurrence graph from."""
    with engine.connect() as conn:
        mined = [r[0].lower() for r in
                 conn.execute(text("SELECT term FROM processed_terms")) if r[0]]
    return [t for t in mined if t in lex][:cap]


def graph_candidates(engine, seeds: list, skip: set, lex: frozenset,
                     k: int, limit: int) -> list:
    """Partners of the geology seeds that look geological (in the lexicon,
    or co-occurring with >= k distinct geology seeds) and aren't already
    requested/mined. Ordered by geology-neighbour count (strongest signal
    first)."""
    if not seeds or limit <= 0:
        return []
    sql = text("""
        SELECT word_2, COUNT(DISTINCT word_1) AS geo_neighbors
        FROM term_cooccurrence
        WHERE word_1 = ANY(:seeds)
        GROUP BY word_2
        ORDER BY geo_neighbors DESC
        LIMIT :cap
    """)
    out = []
    with engine.connect() as conn:
        for r in conn.execute(sql, {"seeds": seeds, "cap": limit * 6}):
            w = (r[0] or "").lower()
            if not w or w in skip or " " in w:
                continue
            if w in lex or r[1] >= k:
                out.append(w)
                if len(out) >= limit:
                    break
    return out


def queue_terms(engine, terms: list, backdate: str) -> int:
    """Insert net-new terms into term_requests (status defaults to
    'pending'). requested_at is backdated so seeded geology is claimed
    ahead of the leftover crawler backlog — the worker claims oldest
    requested_at first. Terms are pre-filtered against existing rows, so
    a plain insert is safe."""
    n = 0
    with engine.begin() as conn:
        for t in terms:
            conn.execute(
                text("INSERT INTO term_requests (term, requested_at) VALUES (:t, :ra)"),
                {"t": t, "ra": backdate},
            )
            n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=200,
                        help="max terms to queue per run (default 200)")
    parser.add_argument("--min-geo-neighbors", type=int, default=3,
                        help="graph-expansion term must co-occur with this many "
                             "geology seeds to count as geological (default 3)")
    parser.add_argument("--seed-cap", type=int, default=500,
                        help="max geology seeds to expand the graph from (bounds "
                             "the cooccurrence query cost; default 500)")
    parser.add_argument("--backdate", default="2000-01-01",
                        help="requested_at stamp for seeded terms so geology is claimed "
                             "ahead of the leftover crawler backlog (default 2000-01-01)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be queued without writing")
    args = parser.parse_args()

    engine = get_engine()
    lex = geo_terms()
    if not lex:
        print("[geo-seeder] lexicon is empty (data/geo_lexicon.txt missing?) "
              "— nothing to do", file=sys.stderr)
        return 1

    seen = existing_terms(engine)

    # 1. Lexicon breadth: net-new geology vocabulary.
    lex_new = [t for t in sorted(lex) if t not in seen]

    # 2. Graph expansion fills whatever batch room the lexicon didn't.
    remaining = max(0, args.batch - len(lex_new))
    graph_new = []
    if remaining > 0:
        seeds = mined_geo_seeds(engine, lex, args.seed_cap)
        graph_new = graph_candidates(
            engine, seeds, seen | set(lex_new), lex,
            args.min_geo_neighbors, remaining,
        )

    batch = (lex_new + graph_new)[:args.batch]
    print(f"[geo-seeder] lexicon net-new={len(lex_new)} "
          f"graph-expansion={len(graph_new)} queuing={len(batch)}")

    if args.dry_run:
        print("  dry-run sample:", ", ".join(batch[:25]))
        return 0

    if not batch:
        print("[geo-seeder] queue already saturated with geology terms — "
              "nothing net-new to add")
        return 0

    queued = queue_terms(engine, batch, args.backdate)
    print(f"[geo-seeder] queued {queued} geology terms (backdated {args.backdate})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
