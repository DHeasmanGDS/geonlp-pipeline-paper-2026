"""Term-request queue writes (single + bulk).

Single-term path: idempotent — re-submitting a term that's already
mined, queued, or running is rejected with an informative outcome
rather than silently re-queued. Bulk path: categorizes each input
against the database state (pending / running / mined / failed) so the
user gets a useful summary back instead of a silent "queued."
"""

from typing import Iterable

from sqlalchemy import text


def queue_term_request(term: str, engine) -> str:
    """Insert (or bump the demand counter on) a single term request.

    Returns a short outcome string so the caller can show the user an
    accurate message:

      'queued'   newly inserted; will be mined
      'pending'  already in the queue; request_count bumped, position kept
      'running'  currently being mined; no-op
      'mined'    already in the corpus; rejected, no-op
      'failed'   previously attempted and failed; counter bumped, NOT
                 auto-requeued (xDD usually has no coverage for these)
      'invalid'  empty after normalization, or longer than 64 chars

    Uses raw SQL throughout rather than the ORM `term_requests` table
    because (a) app/models.py only models a subset of the columns
    (no `status`), and (b) the model's `onupdate=func.now()` on
    `requested_at` would silently bump a term's queue position on every
    counter increment — which would wreck deliberately-set positions
    such as the backdated priority backlog.
    """
    term = (term or "").strip().lower()
    if not term or len(term) > 64:
        return "invalid"

    with engine.begin() as conn:
        # Already in the corpus? processed_terms is the canonical
        # record of every successfully-mined term.
        if conn.execute(
            text("SELECT 1 FROM processed_terms WHERE term = :t"),
            {"t": term},
        ).fetchone():
            return "mined"

        row = conn.execute(
            text("SELECT status FROM term_requests WHERE term = :t"),
            {"t": term},
        ).fetchone()

        if row is None:
            conn.execute(
                text("INSERT INTO term_requests (term) VALUES (:t)"),
                {"t": term},
            )
            return "queued"

        status = row.status
        if status == "done":
            return "mined"
        if status == "running":
            return "running"

        # 'pending' or 'failed': bump the demand counter only. We
        # deliberately do NOT touch requested_at — the term keeps its
        # place in the FIFO queue (important for backdated backlog rows).
        conn.execute(
            text(
                "UPDATE term_requests "
                "SET request_count = request_count + 1 "
                "WHERE term = :t"
            ),
            {"t": term},
        )
        return "failed" if status == "failed" else "pending"


def queue_term_request_bulk(raw_terms: Iterable[str], engine) -> dict:
    """Queue many terms at once, categorizing each against current DB state.

    Returns a dict with five sorted lists of terms:
      queued              newly inserted into term_requests
      already_pending     row exists with status='pending'
      already_running     row exists with status='running'
      already_mined       row exists with status='done' OR term is in processed_terms
      previously_failed   row exists with status='failed' (NOT auto-requeued —
                          the user must explicitly retry these via the
                          recovery path; this avoids futile re-runs for terms
                          xDD genuinely has no snippets for)
      invalid             input strings that couldn't be normalized
                          (empty after strip, or >64 chars)

    Input deduplication is case-insensitive and whitespace-insensitive.
    Inputs are normalized to lowercase before persisting to match the
    rest of the system (the worker stores terms lowercased).
    """
    normalized_to_raw: dict[str, str] = {}
    invalid: list[str] = []

    for raw in raw_terms:
        if not isinstance(raw, str):
            continue
        candidate = raw.strip().lower()
        if not candidate:
            continue
        if len(candidate) > 64:
            invalid.append(raw.strip()[:80])  # cap for display
            continue
        if candidate not in normalized_to_raw:
            normalized_to_raw[candidate] = raw.strip()

    queued: list[str] = []
    already_pending: list[str] = []
    already_running: list[str] = []
    already_mined: list[str] = []
    previously_failed: list[str] = []

    if not normalized_to_raw:
        return {
            "queued": [],
            "already_pending": [],
            "already_running": [],
            "already_mined": [],
            "previously_failed": [],
            "invalid": sorted(set(invalid)),
        }

    term_list = list(normalized_to_raw.keys())

    # Look up current state in one round-trip each.
    existing_status: dict[str, str] = {}
    processed: set[str] = set()

    try:
        with engine.connect() as conn:
            try:
                rows = conn.execute(
                    text("SELECT term, status FROM term_requests WHERE term = ANY(:t)"),
                    {"t": term_list},
                )
                for r in rows:
                    existing_status[r.term] = r.status
            except Exception:
                # Pre-0001 schema: term_requests lacks `status`. Fall back
                # to existence-only check; we'll treat all matches as
                # "already_pending" so we don't double-queue.
                rows = conn.execute(
                    text("SELECT term FROM term_requests WHERE term = ANY(:t)"),
                    {"t": term_list},
                )
                for r in rows:
                    existing_status[r.term] = "pending"

            rows = conn.execute(
                text("SELECT term FROM processed_terms WHERE term = ANY(:t)"),
                {"t": term_list},
            )
            for r in rows:
                processed.add(r.term)
    except Exception:
        # If even existence checks fail (DB unreachable), fall through
        # to insert attempts which will themselves error and surface to
        # the route. Don't silently lie about queueing.
        pass

    # Categorize + insert
    for term in term_list:
        status = existing_status.get(term)
        if term in processed or status == "done":
            already_mined.append(term)
        elif status == "pending":
            already_pending.append(term)
        elif status == "running":
            already_running.append(term)
        elif status == "failed":
            previously_failed.append(term)
        else:
            queue_term_request(term, engine)
            queued.append(term)

    return {
        "queued": sorted(queued),
        "already_pending": sorted(already_pending),
        "already_running": sorted(already_running),
        "already_mined": sorted(already_mined),
        "previously_failed": sorted(previously_failed),
        "invalid": sorted(set(invalid)),
    }
