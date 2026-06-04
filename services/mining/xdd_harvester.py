"""xDD snippet harvester for term-mining.

Adapted from the MSc geonlp notebook's `xdd_api.py::xdd_api_call` — pages
through xDD's `/api/v1/snippets` endpoint following `next_page` cursors,
with bounded retries on transient failures, until the term's snippets are
exhausted.

The literature-search route uses a *separate* xDD client
(`services/xdd.py`) which is capped at 25 snippets per response and
intended for live UI display. This module is for the offline batch mining
job — no cap, no pretty-printing, plain dicts.
"""

from __future__ import annotations

import time
from typing import Iterator

import requests

# xDD's `/api/v1/snippets` endpoint is dead as of 2026-04 — it accepts the
# request and never responds. The non-versioned `/api/snippets` is the
# current working endpoint (same response shape) and is what the portal's
# live literature-search route uses. Confirmed working via direct fetch.
XDD_SNIPPETS_URL = "https://xdd.wisc.edu/api/snippets"
DEFAULT_TIMEOUT = 30

# Retry budget per page. Tuned for "transient flake" but bail-fast on
# sustained outage so a failed cron-spawned miner ends within ~20 min
# (30 retries × ~40s = 1200s) instead of the previous ~3h of
# hammering. The cron retries naturally every 30 min when xDD comes
# back. Reset to 0 after every successful page, so on a healthy mine
# the per-page budget is plenty.
#
# Per-page reset: a multi-day mine of `table` etc. still tolerates
# unlimited intermittent failures over the run, just not 30 in a row
# on the same page.
DEFAULT_RETRY_LIMIT = 30
DEFAULT_BACKOFF_SECONDS = 10

# Snippets endpoint caps page size at 25; full_results=true is required
# to enable pagination via next_page.
DEFAULT_PER_PAGE = 25


class XddHarvestError(RuntimeError):
    """Raised when iter_pages / iter_snippets exhausts its retry budget
    against xDD without finishing the harvest.

    This is distinct from "the term has zero snippets" — a genuine
    zero-results term will exit normally with the page loop running
    cleanly but yielding no docs. This exception means we never got
    reliable success responses (rate-limited, xDD down, network
    broken, etc.) and the caller should mark the term failed with a
    *retryable* error rather than a *terminal* "no coverage" verdict.
    """


def iter_pages(
    term: str,
    *,
    extra_params: dict | None = None,
    headers: dict | None = None,
    retry_limit: int = DEFAULT_RETRY_LIMIT,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    log: callable = print,
) -> Iterator[list[dict]]:
    """Generator that yields one page of `success.data` (a list of docs)
    at a time. Drives pagination via xDD's `next_page` cursor with retry
    backoff per page. Memory stays bounded — the caller never has to
    hold all docs at once.

    This is the building block for the worker's streaming pipeline. The
    legacy `harvest_snippets` (returns a single big list) is a thin
    wrapper around this for callers that *want* the full materialized
    result.
    """
    params: dict = dict(extra_params or {})
    params.setdefault("per_page", DEFAULT_PER_PAGE)
    params.setdefault("full_results", "true")
    params["term"] = term

    api_url = XDD_SNIPPETS_URL
    headers = headers or {}
    retries = 0
    pages = 0

    log(f"[xdd] '{term}': starting harvest from {api_url}")

    while True:
        try:
            resp = requests.get(api_url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            retries += 1
            if retries % 10 == 0:
                log(f"[xdd] '{term}': retry {retries}/{retry_limit} after {type(e).__name__}: {e}")
            if retries >= retry_limit:
                log(f"[xdd] giving up after {retries} retries on '{term}': {e}")
                raise XddHarvestError(
                    f"giving up after {retries} retries on '{term}' "
                    f"({type(e).__name__}: {e})"
                )
            time.sleep(backoff_seconds)
            continue

        if resp.status_code != 200:
            retries += 1
            if retries % 10 == 0:
                log(f"[xdd] '{term}': retry {retries}/{retry_limit} after HTTP {resp.status_code}")
            if retries >= retry_limit:
                log(f"[xdd] HTTP {resp.status_code} for '{term}', exceeded retry limit")
                raise XddHarvestError(
                    f"giving up after {retries} retries on '{term}' "
                    f"(HTTP {resp.status_code})"
                )
            time.sleep(backoff_seconds)
            continue

        try:
            data = resp.json()
        except ValueError:
            retries += 1
            if retries >= retry_limit:
                log(f"[xdd] invalid JSON for '{term}', exceeded retry limit")
                raise XddHarvestError(
                    f"giving up after {retries} retries on '{term}' "
                    f"(invalid JSON in response)"
                )
            time.sleep(backoff_seconds)
            continue

        # xDD's HTTP layer can return 200 with a JSON body that lacks
        # the `success` block during partial outages (e.g. Elasticsearch
        # `cluster_block_exception` while the index is recovering). In
        # that case `error` is present at the top level. Treat as a
        # retryable harvester failure — NOT a clean "no coverage" exit.
        if "success" not in data:
            err_blob = data.get("error")
            if isinstance(err_blob, dict):
                err_msg = err_blob.get("message") or err_blob.get("details") or str(err_blob)
            else:
                err_msg = str(err_blob) if err_blob else "no `success` key in response"
            retries += 1
            if retries % 10 == 0:
                log(f"[xdd] '{term}': retry {retries}/{retry_limit} after "
                    f"backend error: {err_msg[:200]}")
            if retries >= retry_limit:
                log(f"[xdd] '{term}': backend errored {retries} times, giving up: {err_msg[:200]}")
                raise XddHarvestError(
                    f"xDD HTTP 200 but missing `success` block for '{term}' "
                    f"after {retries} retries (last error: {err_msg[:200]})"
                )
            time.sleep(backoff_seconds)
            continue

        success = data["success"] or {}
        page_docs = success.get("data") or []
        pages += 1
        yield page_docs

        next_page = success.get("next_page")
        if not next_page:
            return
        api_url = next_page
        # The next_page URL already encodes term + cursor, so drop our
        # params dict for subsequent calls.
        params = {}
        retries = 0  # reset retry budget per page


def get_total_hits(term: str, extra_params: dict | None = None) -> int | None:
    """Probe xDD for the total snippet count of a term without mining it.

    Issues a single `per_page=1` request and reads `success.hits` from
    the response. Returns the hit count (int), or None if xDD is
    unreachable / the response is malformed / the hits field is missing.

    Used by the mining worker as a pre-flight check: if hits exceeds a
    configured threshold (SNAPSHOT_MAX_SNIPPETS_PER_TERM), the term is
    too common to mine reliably under the current memory budget — the
    streaming Counter's vocab would exceed pod memory mid-mine and
    OOMKill, leaving a zombie row. Better to decline up-front with a
    terminal "too common" error than to OOMKill and orphan.
    """
    params = {
        "term": term,
        "per_page": 1,
        "full_results": "true",
    }
    if extra_params:
        params.update(extra_params)
    try:
        resp = requests.get(
            XDD_SNIPPETS_URL,
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        success = body.get("success") or {}
        hits = success.get("hits")
        return int(hits) if hits is not None else None
    except (requests.RequestException, ValueError, TypeError):
        # Network error, JSON parse failure, or weird types — treat as
        # "couldn't probe" and let the caller decide what to do.
        return None


def iter_snippets(
    term: str,
    *,
    progress_every: int = 1000,
    log: callable = print,
    **kwargs,
) -> Iterator[str]:
    """Streaming generator: yields each xDD snippet (highlight string) as
    it's pulled, never accumulating docs in memory. Drops empty
    highlights. Logs progress every `progress_every` snippets.

    Use this in the mining worker so memory stays bounded regardless of
    how many snippets a popular term has (mineral has 480k+, water/copper
    likely similar).
    """
    n = 0
    last_log_at = 0
    pages = 0
    start_time = time.time()

    for page_docs in iter_pages(term, log=log, **kwargs):
        pages += 1
        for doc in page_docs:
            highlights = doc.get("highlight") or []
            if isinstance(highlights, str):
                highlights = [highlights]
            for h in highlights:
                if not h:
                    continue
                n += 1
                yield h
        # Log first page always (connectivity check), then every N snippets.
        if pages == 1 or n - last_log_at >= progress_every:
            log(f"[xdd] '{term}': page {pages}, {n} snippets streamed so far")
            last_log_at = n

    runtime = time.time() - start_time
    log(f"[xdd] '{term}': finished streaming in {runtime:.1f}s with {n} snippets across {pages} pages")


def harvest_snippets(
    term: str,
    **kwargs,
) -> tuple[list[dict], float]:
    """Legacy materializing harvester — returns (docs, runtime).

    Builds the full doc list in memory; only safe for terms with a
    bounded number of snippets. The streaming worker now uses
    `iter_snippets` instead. Kept for any external caller / test that
    expects the original API.
    """
    log = kwargs.get("log") or print
    docs: list[dict] = []
    start_time = time.time()
    log(f"[xdd] '{term}': harvesting (materialized)")
    for page_docs in iter_pages(term, **kwargs):
        docs.extend(page_docs)
    runtime = time.time() - start_time
    log(f"[xdd] '{term}': materialized {len(docs)} docs in {runtime:.1f}s")
    return docs, runtime


def explode_highlights(docs: list[dict]) -> Iterator[dict]:
    """Flatten xDD docs into per-snippet rows.

    A single xDD doc can have multiple `highlight` strings (one per
    match in the document). The streaming worker no longer uses this
    (it consumes highlights inline via `iter_snippets`), but the pure
    schema-flattening logic is still useful for tests and any external
    caller that already has a materialized doc list.
    """
    for doc in docs:
        highlights = doc.get("highlight") or []
        if isinstance(highlights, str):
            highlights = [highlights]
        for h in highlights:
            if not h:
                continue
            yield {
                "_gddid": doc.get("_gddid") or doc.get("gddid") or "",
                "highlight": h,
                "doi": doc.get("doi") or "",
                "title": doc.get("title") or "",
                "publisher": doc.get("publisher") or "",
                "pubname": doc.get("pubname") or doc.get("journal") or "",
                "coverDate": doc.get("coverDate") or "",
            }


def explode_highlights(docs: list[dict]) -> Iterator[dict]:
    """Flatten xDD docs into per-snippet rows.

    A single xDD doc can have multiple `highlight` strings (one per match
    in the document). Counts and co-occurrence work at the snippet level,
    so we explode here once.

    Yields dicts with: `_gddid`, `highlight`, `doi`, `title`, `publisher`,
    `pubname`, `coverDate`. Drops snippets with empty/missing highlights.
    """
    for doc in docs:
        highlights = doc.get("highlight") or []
        if isinstance(highlights, str):
            highlights = [highlights]
        for h in highlights:
            if not h:
                continue
            yield {
                "_gddid": doc.get("_gddid") or doc.get("gddid") or "",
                "highlight": h,
                "doi": doc.get("doi") or "",
                "title": doc.get("title") or "",
                "publisher": doc.get("publisher") or "",
                "pubname": doc.get("pubname") or doc.get("journal") or "",
                "coverDate": doc.get("coverDate") or "",
            }
