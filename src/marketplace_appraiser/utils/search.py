"""Centralized web search — Tavily primary, DuckDuckGo fallback.

All results are normalized to dicts with keys: title, body, href.
"""

import os
import time
import threading

from ddgs import DDGS


# Module-level rate limiter — 1 search per second across all threads
_lock = threading.Lock()
_last_search_time: float = 0.0
_RATE_LIMIT_SECONDS = 1.0

_MAX_RETRIES = 2
_INITIAL_BACKOFF = 2.0

# Lazy-initialized Tavily client
_tavily_client = None
_tavily_checked = False


def _get_tavily_client():
    """Return a TavilyClient if the key is set, else None."""
    global _tavily_client, _tavily_checked
    if _tavily_checked:
        return _tavily_client
    _tavily_checked = True

    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return None

    try:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=api_key)
        print("  [search] Using Tavily search API")
    except ImportError:
        print("  [search] tavily-python not installed — using DuckDuckGo")
    return _tavily_client


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Search via Tavily and normalize results to {title, body, href}."""
    client = _get_tavily_client()
    if client is None:
        return None  # signal to fall back

    try:
        response = client.search(query, max_results=max_results)
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "body": r.get("content", ""),
                "href": r.get("url", ""),
            })
        return results
    except Exception as e:
        print(f"  [search] Tavily failed for '{query[:60]}': {e}")
        return None  # signal to fall back to DDG


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo text search with rate limiting and retry."""
    global _last_search_time

    for attempt in range(1, _MAX_RETRIES + 2):  # 1 initial + 2 retries
        # Rate limit
        with _lock:
            now = time.monotonic()
            elapsed = now - _last_search_time
            if elapsed < _RATE_LIMIT_SECONDS:
                time.sleep(_RATE_LIMIT_SECONDS - elapsed)
            _last_search_time = time.monotonic()

        try:
            ddgs = DDGS()
            results = ddgs.text(query, max_results=max_results)
            return results
        except Exception as e:
            if attempt > _MAX_RETRIES:
                print(f"  Search failed after {_MAX_RETRIES + 1} attempts for "
                      f"'{query[:60]}': {e}")
                return []
            wait = _INITIAL_BACKOFF * (2 ** (attempt - 1))
            print(f"  Search retry {attempt}/{_MAX_RETRIES} for "
                  f"'{query[:60]}' — waiting {wait}s...")
            time.sleep(wait)

    return []


def safe_search(query: str, max_results: int = 5) -> list[dict]:
    """Web search with Tavily as primary and DuckDuckGo as fallback.

    Returns list of result dicts (keys: title, body, href), or []
    on total failure.
    """
    # Try Tavily first
    results = _tavily_search(query, max_results)
    if results is not None:
        return results

    # Fall back to DuckDuckGo
    return _ddg_search(query, max_results)
