"""Term-class assignment for the mining queue.

Each `term_requests` row gets a `term_class` ('small'/'medium'/'large'/
'oversized') determined by the term's xDD snippet count. Workers then
claim rows filtered by class so a mega-term cannot monopolize a slot
that should be turning over fast small-term jobs.

This module is the pure logic — DB I/O and CronJob glue live in
`scripts/classify_pending_terms.py`. Splitting them keeps the
classification rule unit-testable and lets the worker do an inline
on-demand classification if it ever picks up an unclassified row.

Flow:

    +---------+   probe xDD     +-----------+    classify_hits()    +-----------+
    | term    |---------------->| hits: int |---------------------->| 'small'   |
    | request |  get_total_hits |           | mining_config         | 'medium'  |
    +---------+                 +-----------+                       | 'large'   |
                                                                    | 'oversized'|
                                                                    +-----------+
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.mining.xdd_harvester import get_total_hits
from services.mining_config import (
    classify_hits,
    xdd_snapshot_params,
)


@dataclass(frozen=True)
class ClassifyResult:
    """Outcome of classifying a single term.

    `term_class` is None when xDD was unreachable for the probe; the
    caller should leave the DB row unclassified and let the next
    classifier tick try again rather than guessing.
    """
    term: str
    hits: Optional[int]
    term_class: Optional[str]

    @property
    def is_classified(self) -> bool:
        return self.term_class is not None


def classify_term(term: str) -> ClassifyResult:
    """Probe xDD once for `term` and return its class.

    Single network call; no DB I/O. Use this from the classifier
    CronJob, or inline from the worker when it grabs an unclassified
    row. The xDD snapshot params (max_acquired, fragment_limit) are
    applied automatically so hit counts agree with mining-time counts.

    Returns a ClassifyResult; a None `term_class` means "couldn't
    determine — try again later." It is NEVER an error condition that
    should be persisted as a class.
    """
    hits = get_total_hits(term, extra_params=xdd_snapshot_params())
    cls = classify_hits(hits)
    return ClassifyResult(term=term, hits=hits, term_class=cls)
