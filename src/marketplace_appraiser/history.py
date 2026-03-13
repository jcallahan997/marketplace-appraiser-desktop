"""Run history — save/load/list appraisal runs as JSON files.

Each run is stored as a JSON file in ``output/history/<run_id>.json``.
The JSON contains the full pipeline state plus run metadata (timestamps,
status, report HTML).
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


HISTORY_DIR = Path("output/history")


def _ensure_dir() -> None:
    """Create the history directory if it doesn't exist."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


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
) -> None:
    """Update an existing run record."""
    path = HISTORY_DIR / f"{run_id}.json"
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
    path.write_text(json.dumps(record, indent=2))


def get_run(run_id: str) -> Optional[dict]:
    """Load a single run record by ID."""
    path = HISTORY_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def list_runs(limit: int = 50) -> list[dict]:
    """List recent runs, newest first.

    Returns a list of summary dicts (no full state or HTML — just metadata).
    """
    _ensure_dir()
    runs = []
    for path in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        try:
            record = json.loads(path.read_text())
            runs.append({
                "run_id": record["run_id"],
                "listing_url": record.get("listing_url", ""),
                "item_name": record.get("state", {}).get("item_name", ""),
                "status": record.get("status", "unknown"),
                "started_at": record.get("started_at"),
                "finished_at": record.get("finished_at"),
                "report_subject": record.get("report_subject"),
                "recommendation": _extract_recommendation(record),
            })
        except (json.JSONDecodeError, KeyError):
            continue
        if len(runs) >= limit:
            break
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
