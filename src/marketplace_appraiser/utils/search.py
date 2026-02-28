"""Centralized DuckDuckGo search with rate limiting and retry."""

import time
import threading

from ddgs import DDGS


# Module-level rate limiter — 1 search per second across all threads
_lock = threading.Lock()
_last_search_time: float = 0.0
_RATE_LIMIT_SECONDS = 1.0

_MAX_RETRIES = 2
_INITIAL_BACKOFF = 2.0


def safe_search(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo text search with rate limiting and retry.

    - Enforces a minimum 1-second gap between searches (thread-safe).
    - Retries up to 2 times with exponential backoff on exception.
    - Returns list of result dicts (keys: title, body, href), or []
      on total failure.
    """
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
