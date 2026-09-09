"""Bundled geology term lexicon, shared by the geology seeder
(scripts/geology_seeder.py) and the auto-queue gate in the read routes.

Loaded once from data/geo_lexicon.txt (single-word geology terms:
minerals, rocks, deposit/alteration/structural/petrologic vocab, and the
geologic time scale). Two uses:

  * is_geological(term): gate auto-queue-on-view so a crawler hitting
    arbitrary /statistics pages can't flood the queue with off-domain
    (biology, common-word) terms — only recognized geology terms enqueue.
  * geo_terms(): breadth seed + membership test for the geology seeder.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import FrozenSet

_LEXICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "geo_lexicon.txt",
)


@lru_cache(maxsize=1)
def geo_terms() -> FrozenSet[str]:
    """The lexicon as a lowercase frozenset. Cached for the process
    lifetime. Returns an empty set if the file is missing — fail-open so
    a packaging slip degrades the gate to 'never auto-queue' rather than
    breaking the request routes."""
    try:
        with open(_LEXICON_PATH, encoding="utf-8") as f:
            return frozenset(
                line.strip().lower() for line in f if line.strip()
            )
    except OSError:
        return frozenset()


def is_geological(term: str) -> bool:
    """True if `term` is a recognized single-word geology term."""
    return (term or "").strip().lower() in geo_terms()
