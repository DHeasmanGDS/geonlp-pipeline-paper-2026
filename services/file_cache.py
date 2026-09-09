"""Filesystem cache helpers for generated artifacts (wordclouds, network HTML).

Two responsibilities:

1. **Stable hashing of inputs** — `cache_key(*parts)` produces a short hex
   digest. The same inputs always map to the same filename, so repeat
   requests are served by the existing file with no regeneration.

2. **Bounded retention** — `prune_old_files(dir, days)` removes files older
   than `days`. Called from the route just before generating a new file, so
   the disk never grows unboundedly. Cache hits skip pruning, so they stay
   fast.

Concurrency: two simultaneous requests with the same hash may both see
"file missing" and both regenerate. The losing write is overwritten by an
identical payload — benign. Concurrent unlinks during pruning are also
safe; the loser's `FileNotFoundError` is swallowed.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Iterable

DEFAULT_MAX_AGE_DAYS = 30


def cache_key(*parts: object) -> str:
    """Return a stable 16-char hex digest of the joined parts.

    Strings are case- and whitespace-stripped to normalize trivial variants;
    other types are passed through `repr()` for stability.
    """
    normalized: list[str] = []
    for p in parts:
        if isinstance(p, str):
            normalized.append(p.strip().lower())
        else:
            normalized.append(repr(p))
    raw = "|".join(normalized).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def touch(path: str | Path) -> None:
    """Update mtime so this file resists pruning. Best-effort."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def prune_old_files(
    directory: str | Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    suffixes: Iterable[str] | None = None,
) -> int:
    """Delete files in `directory` older than `max_age_days`.

    Returns the number of files removed. Best-effort: swallows OSError on
    individual files (e.g. concurrent removal) so a single bad file doesn't
    abort the sweep.
    """
    d = Path(directory)
    if not d.exists():
        return 0

    cutoff = time.time() - max_age_days * 86400
    suffix_set = {s.lower() for s in suffixes} if suffixes else None
    removed = 0

    for entry in d.iterdir():
        if not entry.is_file():
            continue
        if suffix_set and entry.suffix.lower() not in suffix_set:
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            pass

    return removed
