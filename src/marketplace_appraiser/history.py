"""Run history — save/load/list appraisal runs as JSON files.

Each run is stored as a JSON file in ``output/history/<run_id>.json``.
The JSON contains the full pipeline state plus run metadata (timestamps,
status, report HTML).
"""

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional


# Resolve relative to the project root (3 levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = _PROJECT_ROOT / "output" / "history"


def _ensure_dir() -> None:
    """Create the history directory if it doesn't exist."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


# Per-run locks to prevent concurrent read-modify-write races
_run_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_run_lock(run_id: str) -> threading.Lock:
    """Get (or create) a threading lock for a specific run."""
    with _locks_lock:
        if run_id not in _run_locks:
            _run_locks[run_id] = threading.Lock()
        return _run_locks[run_id]


def _sanitize_state(state: dict) -> dict:
    """Make pipeline state JSON-serializable.

    Converts Path objects to strings, drops non-serializable values.
    """
    clean: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, Path):
            clean[key] = str(value)
        elif isinstance(value, list):
            clean[key] = [
                str(v) if isinstance(v, Path) else v for v in value
            ]
        else:
            try:
                json.dumps(value)
                clean[key] = value
            except (TypeError, ValueError):
                clean[key] = str(value)
    return clean


def create_run(listing_url: str, send_email: bool = False) -> str:
    """Create a new run record and return its run_id."""
    _ensure_dir()
    run_id = str(uuid.uuid4())[:8]
    record = {
        "run_id": run_id,
        "listing_url": listing_url,
        "send_email": send_email,
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "error": None,
        "state": {},
        "report_html": None,
        "report_subject": None,
    }
    path = HISTORY_DIR / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2))
    return run_id


def update_run(
    run_id: str,
    *,
    status: Optional[str] = None,
    state: Optional[dict] = None,
    report_html: Optional[str] = None,
    report_subject: Optional[str] = None,
    error: Optional[str] = None,
    **extra: Any,
) -> None:
    """Update an existing run record.

    Any extra keyword arguments are stored directly on the record
    (e.g. ``langfuse_trace_id``, ``langfuse_total_cost``).
    """
    path = HISTORY_DIR / f"{run_id}.json"
    lock = _get_run_lock(run_id)
    with lock:
        if not path.exists():
            return
        record = json.loads(path.read_text())
        if status is not None:
            record["status"] = status
            if status in ("completed", "failed"):
                record["finished_at"] = time.time()
        if state is not None:
            record["state"] = _sanitize_state(state)
        if report_html is not None:
            record["report_html"] = report_html
        if report_subject is not None:
            record["report_subject"] = report_subject
        if error is not None:
            record["error"] = error
        # Store any extra fields (Langfuse metrics, etc.)
        for key, value in extra.items():
            record[key] = value
        path.write_text(json.dumps(record, indent=2))


def get_run(run_id: str) -> Optional[dict]:
    """Load a single run record by ID."""
    path = HISTORY_DIR / f"{run_id}.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _item_name_fallback(record: dict) -> str:
    """Extract a display name for the run, with fallbacks."""
    # 1. Try the scraped item name
    name = record.get("state", {}).get("item_name", "")
    if name:
        return name
    # 2. Try the report subject: "[REC] Item Name — $Price ..."
    subject = record.get("report_subject", "") or ""
    if "] " in subject:
        after_bracket = subject.split("] ", 1)[1]
        # Strip everything after " — " or " - "
        for sep in (" — ", " - ", " – "):
            if sep in after_bracket:
                after_bracket = after_bracket.split(sep, 1)[0]
        if after_bracket.strip():
            return after_bracket.strip()
    # 3. Try to extract from the listing URL
    url = record.get("listing_url", "")
    if "/item/" in url:
        # URLs look like .../marketplace/item/123456789/
        return f"Listing #{url.split('/item/')[-1].strip('/').split('/')[0][:12]}"
    return ""


# Runs stuck as "running" for more than this many seconds are marked stale.
_STALE_THRESHOLD_SECS = 4 * 3600  # 4 hours


def list_runs(limit: int = 50) -> list[dict]:
    """List recent runs, newest first (sorted by started_at).

    Returns a list of summary dicts (no full state or HTML — just metadata).
    Runs stuck as "running" for >4 hours are automatically marked as "stale".
    """
    _ensure_dir()
    # Load all records first, then sort by started_at
    records = []
    for path in HISTORY_DIR.glob("*.json"):
        try:
            record = json.loads(path.read_text())
            records.append((path, record))
        except (json.JSONDecodeError, KeyError):
            continue

    # Sort by started_at descending (newest first)
    records.sort(key=lambda x: x[1].get("started_at", 0) or 0, reverse=True)

    now = time.time()
    runs = []
    for path, record in records[:limit]:
        status = record.get("status", "unknown")
        # Auto-expire stale "running" runs
        if status == "running":
            started = record.get("started_at", 0) or 0
            if now - started > _STALE_THRESHOLD_SECS:
                status = "stale"
                # Persist the fix so it doesn't recalculate every time
                record["status"] = "stale"
                record["finished_at"] = record.get("started_at", now)
                record["error"] = "Run expired (server restarted or crashed)"
                try:
                    path.write_text(json.dumps(record, indent=2))
                except OSError:
                    pass

        runs.append({
            "run_id": record["run_id"],
            "listing_url": record.get("listing_url", ""),
            "item_name": _item_name_fallback(record),
            "status": status,
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
            "report_subject": record.get("report_subject"),
            "recommendation": _extract_recommendation(record),
            # Langfuse metrics (populated after pipeline + Langfuse fetch)
            "langfuse_total_cost": record.get("langfuse_total_cost"),
            "langfuse_latency": record.get("langfuse_latency"),
            "langfuse_trace_url": record.get("langfuse_trace_url"),
        })
    return runs


def _extract_recommendation(record: dict) -> str:
    """Extract the recommendation badge from a run record."""
    subject = record.get("report_subject", "") or ""
    # Subject format: [RECOMMENDATION] Item — $Price ...
    if subject.startswith("["):
        end = subject.find("]")
        if end > 0:
            return subject[1:end].upper()
    return ""


def get_run_preview(run_id: str) -> Optional[str]:
    """Get the email HTML preview for a run. Returns None if not available."""
    record = get_run(run_id)
    if not record:
        return None
    return record.get("report_html")
