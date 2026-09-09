"""xDD (formerly GeoDeepDive) snippets API client.

Docs: https://xdd.wisc.edu/api
Snippets endpoint: https://xdd.wisc.edu/api/snippets?term=<query>
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
import requests

XDD_SNIPPETS_URL = "https://xdd.wisc.edu/api/snippets"
XDD_DOMAIN_PREFIX = "https://xdd.wisc.edu/"
DEFAULT_TIMEOUT = 15  # seconds
TIMELINE_TIMEOUT = 8  # tighter per-request budget for the parallel sweep


def search_snippets(
    term: str,
    *,
    limit: int = 25,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    inclusive: bool = False,
    full_results: bool = True,
    clean: bool = True,
    next_page_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Query the xDD snippets endpoint and return a normalized result dict.

    If `next_page_url` is provided, that exact URL is fetched (used by
    the "Load more" button to follow xDD's cursor-based pagination).
    Otherwise we build the initial query from `term` plus the optional
    filters.

    Returns:
        {
            "success": bool,
            "term": str,
            "total_hits": int | None,
            "results": list of normalized hit dicts,
            "next_page_url": str | None,   # cursor for the next page
            "error": str | None,
        }

    Each hit contains: gddid, title, authors (str), publisher, pubname, doi,
    url, year, highlight (list[str]).
    """
    out: Dict[str, Any] = {
        "success": False,
        "term": term,
        "total_hits": None,
        "results": [],
        "next_page_url": None,
        "error": None,
    }

    if next_page_url:
        # Defense against SSRF: only follow URLs that came from xDD.
        if not next_page_url.startswith(XDD_DOMAIN_PREFIX):
            out["error"] = "Refusing to follow non-xDD next_page URL."
            return out
        url = next_page_url
        params: Dict[str, str] = {}
    else:
        url = XDD_SNIPPETS_URL
        params = {
            "term": term,
            "full_results": "true" if full_results else "false",
            "clean": "true" if clean else "false",
        }
        if limit:
            # xDD caps per_page at 25.
            params["per_page"] = str(min(int(limit), 25))
        if inclusive:
            # All search words must appear in the snippet (instead of any).
            params["inclusive"] = "true"
        if min_year:
            params["min_published"] = str(int(min_year))
        if max_year:
            params["max_published"] = str(int(max_year))

    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        out["error"] = f"xDD request failed: {e}"
        return out

    try:
        payload = resp.json()
    except ValueError as e:
        out["error"] = f"xDD returned invalid JSON: {e}"
        return out

    # The xDD wrapper is typically {"success": {"data": [...], "hits": N, "v": 2, "next_page": "..."}}
    success_block = payload.get("success") or payload.get("data") or {}
    next_page: Optional[str] = None
    if isinstance(success_block, list):
        # Some endpoints return a bare list.
        raw_hits = success_block
        out["total_hits"] = len(raw_hits)
    elif isinstance(success_block, dict):
        raw_hits = success_block.get("data", []) or []
        out["total_hits"] = success_block.get("hits") or len(raw_hits)
        np = success_block.get("next_page")
        if isinstance(np, str) and np.startswith(XDD_DOMAIN_PREFIX):
            next_page = np
    else:
        out["error"] = "Unexpected xDD response shape."
        return out

    out["success"] = True
    out["results"] = [_normalize_hit(h) for h in raw_hits[:limit] if isinstance(h, dict)]
    out["next_page_url"] = next_page
    return out


def _hits_for_year(term: str, year: int) -> tuple[int, int]:
    """Hit count for a term in one publication year. xDD's snippets
    endpoint exposes `success.hits` even when `per_page=1`, so we just
    ask for one snippet and read the total."""
    try:
        resp = requests.get(
            XDD_SNIPPETS_URL,
            params={
                "term": term,
                "min_published": str(year),
                "max_published": str(year),
                "per_page": "1",
                "full_results": "true",
            },
            timeout=TIMELINE_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return (year, 0)
    success = payload.get("success") or {}
    if isinstance(success, dict):
        hits = success.get("hits")
        if isinstance(hits, (int, float)):
            return (year, int(hits))
        # Some responses lack `hits` and just have `data`. Fall back.
        data = success.get("data") or []
        return (year, len(data))
    return (year, 0)


def count_snippets_per_year(
    term: str,
    start: int,
    end: int,
    max_workers: int = 8,
) -> Dict[int, int]:
    """Hit counts per publication year for `term`, parallelized across
    threads (xDD is the I/O bottleneck — sequential would take 30+s for
    a typical 25-year span). Returns a dict {year: count} for every year
    in [start, end] inclusive. Years where xDD errored or returned 0
    appear with count=0 rather than being dropped — keeps the chart
    aligned with the requested range.
    """
    if start > end:
        start, end = end, start
    years = list(range(start, end + 1))
    out: Dict[int, int] = {y: 0 for y in years}

    if not term.strip() or not years:
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_hits_for_year, term, y) for y in years]
        for fut in as_completed(futures):
            year, count = fut.result()
            out[year] = count

    return out


def _normalize_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten an xDD hit into a stable shape for the template."""
    highlight = hit.get("highlight") or hit.get("highlights") or []
    if isinstance(highlight, str):
        highlight = [highlight]

    authors_raw = hit.get("authors") or []
    if isinstance(authors_raw, list):
        authors_str = ", ".join(
            a.get("name") if isinstance(a, dict) else str(a) for a in authors_raw
        )
    else:
        authors_str = str(authors_raw)

    # Year may be in coverDate, year, or pubdate
    year: Optional[str] = None
    for k in ("year", "coverDate", "pubdate"):
        v = hit.get(k)
        if v:
            year = str(v)[:4] if len(str(v)) >= 4 else str(v)
            break

    # URL handling — xDD returns a list of URL dicts.
    url = ""
    raw_url = hit.get("url") or hit.get("URL")
    if isinstance(raw_url, list) and raw_url:
        first = raw_url[0]
        url = first.get("url", "") if isinstance(first, dict) else str(first)
    elif isinstance(raw_url, str):
        url = raw_url

    doi = hit.get("doi") or ""
    if isinstance(doi, list):
        doi = doi[0] if doi else ""

    return {
        "gddid": hit.get("_gddid") or hit.get("gddid") or "",
        "title": hit.get("title") or "(untitled)",
        "authors": authors_str,
        "publisher": hit.get("publisher") or "",
        "pubname": hit.get("pubname") or hit.get("journal") or "",
        "doi": doi,
        "url": url,
        "year": year,
        "highlight": [str(h) for h in highlight if h],
    }
