"""FastAPI server for the Marketplace Appraiser dashboard.

Provides REST endpoints and WebSocket streaming for real-time pipeline progress.

Usage:
    uvicorn marketplace_appraiser.server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import io
import os
import re
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from marketplace_appraiser.graph import (
    PIPELINE_NODES,
    STEP_LABELS,
    build_graph,
)
from marketplace_appraiser.history import (
    create_run,
    get_run,
    get_run_preview,
    list_runs,
    update_run,
)
from marketplace_appraiser.nodes.email_report import (
    build_report,
    send_report_email,
)

load_dotenv(override=False)

# ---------------------------------------------------------------------------
# Langfuse observability (optional — enabled when LANGFUSE_PUBLIC_KEY is set)
# ---------------------------------------------------------------------------

_langfuse_enabled = bool(os.getenv("LANGFUSE_PUBLIC_KEY"))

if _langfuse_enabled:
    try:
        from langfuse import get_client as _get_langfuse_client
        from langfuse.langchain import CallbackHandler as LangfuseHandler
    except ImportError:
        _langfuse_enabled = False

# ---------------------------------------------------------------------------
# WebSocket stdout capture
# ---------------------------------------------------------------------------

# Step pattern that nodes print: "STEP N: ..."
_STEP_PATTERN = re.compile(r"^=+\nSTEP (\d+):|^STEP (\d+):")


# Thread-local storage: each pipeline thread stores its run_id here
# so the shared stdout writer can tag messages correctly.
_thread_local = threading.local()


class WebSocketWriter(io.TextIOBase):
    """Replaces sys.stdout to capture prints AND broadcast to WebSocket clients.

    Uses thread-local storage to determine which run_id the current thread
    belongs to, enabling concurrent pipeline runs.
    """

    def __init__(self, original_stdout, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._original = original_stdout
        self._queue = queue
        self._loop = loop

    def write(self, text: str) -> int:
        if text and text.strip():
            self._original.write(text)
            run_id = getattr(_thread_local, "run_id", None)
            try:
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait,
                    {"type": "stdout", "text": text.rstrip(), "run_id": run_id},
                )
            except RuntimeError:
                pass  # loop closed
        elif text:
            self._original.write(text)
        return len(text) if text else 0

    def flush(self):
        self._original.flush()

    def fileno(self):
        return self._original.fileno()

    @property
    def encoding(self):
        return self._original.encoding

    def isatty(self):
        return False


# ---------------------------------------------------------------------------
# Per-run state tracking
# ---------------------------------------------------------------------------

class RunState:
    """Tracks the state of a single pipeline run."""

    def __init__(self, run_id: str, total_steps: int = 7):
        self.run_id = run_id
        self.current_step: int = 0
        self.total_steps: int = total_steps
        self.thread: Optional[threading.Thread] = None
        self.log_buffer: list[dict] = []

    @property
    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class PipelineManager:
    """Manages multiple concurrent pipeline runs and their WebSocket broadcast."""

    def __init__(self):
        self.queue: Optional[asyncio.Queue] = None
        self._clients: set[WebSocket] = set()
        self._runs: dict[str, RunState] = {}  # run_id -> RunState
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """True if any pipeline is currently running."""
        with self._lock:
            return any(r.is_alive for r in self._runs.values())

    @property
    def active_run_ids(self) -> list[str]:
        with self._lock:
            return [rid for rid, r in self._runs.items() if r.is_alive]

    def start_run(self, run_id: str, total_steps: int = 7) -> RunState:
        """Register a new run."""
        state = RunState(run_id, total_steps)
        with self._lock:
            self._runs[run_id] = state
        return state

    def finish_run(self, run_id: str):
        """Mark a run as finished (keep its buffer for late-connecting clients)."""
        # Don't remove — keep the log buffer around for replay
        pass

    def get_run(self, run_id: str) -> Optional[RunState]:
        with self._lock:
            return self._runs.get(run_id)

    def cleanup_old_runs(self, keep: int = 10):
        """Remove old finished run buffers to prevent memory leaks."""
        with self._lock:
            finished = [
                (rid, r) for rid, r in self._runs.items()
                if not r.is_alive
            ]
            # Keep the most recent `keep` finished runs
            if len(finished) > keep:
                # Sort by last log timestamp or just drop oldest
                for rid, _ in finished[:-keep]:
                    del self._runs[rid]

    def reset(self):
        """Reset all state (for force-reset)."""
        with self._lock:
            self._runs.clear()

    async def broadcast(self, message: dict):
        """Send a message to all connected WebSocket clients.

        Also stores the message in the appropriate run's log buffer.
        """
        run_id = message.get("run_id")
        if run_id and message.get("type") in (
            "stdout", "step_start", "step_complete",
            "pipeline_complete", "error",
        ):
            run_state = self.get_run(run_id)
            if run_state:
                run_state.log_buffer.append(message)
                # Cap log buffer to prevent unbounded memory growth
                if len(run_state.log_buffer) > 5000:
                    run_state.log_buffer = run_state.log_buffer[-5000:]

        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def replay_buffer(self, ws: WebSocket, run_id: Optional[str] = None):
        """Send buffered log history to a newly connected client.

        If run_id is given, replay only that run's buffer.
        Otherwise replay the most recent active run.
        """
        target_run = None
        if run_id:
            target_run = self.get_run(run_id)
        else:
            # Find most recent active run, or most recent finished run
            active = self.active_run_ids
            if active:
                target_run = self.get_run(active[-1])

        if not target_run or not target_run.log_buffer:
            return

        for msg in target_run.log_buffer:
            try:
                await ws.send_json(msg)
            except Exception:
                break


pipeline_mgr = PipelineManager()


# ---------------------------------------------------------------------------
# Pipeline thread runner
# ---------------------------------------------------------------------------

def _run_pipeline_thread(
    listing_url: str,
    run_id: str,
    send_email: bool,
    email_to: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
):
    """Run the appraisal pipeline in a background thread.

    Captures stdout via thread-local run_id tagging, emits node events,
    and saves results to history. Safe for concurrent execution.
    """
    # Tag this thread so the shared WebSocketWriter knows which run_id
    _thread_local.run_id = run_id

    # Install shared stdout interceptor (idempotent — only first thread installs it)
    if not isinstance(sys.stdout, WebSocketWriter):
        sys.stdout = WebSocketWriter(sys.__stdout__, queue, loop)

    run_state = pipeline_mgr.get_run(run_id)

    def on_node_start(node_name: str, step_num: int):
        if run_state:
            run_state.current_step = step_num
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "step_start",
                "run_id": run_id,
                "node": node_name,
                "step": step_num,
                "label": STEP_LABELS.get(node_name, node_name),
            },
        )

    def on_node_end(node_name: str, step_num: int):
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "step_complete",
                "run_id": run_id,
                "node": node_name,
                "step": step_num,
                "label": STEP_LABELS.get(node_name, node_name),
            },
        )

    try:
        # Ensure output directory exists (use absolute path)
        _project_root = Path(__file__).resolve().parent.parent.parent
        (_project_root / "output" / "images").mkdir(parents=True, exist_ok=True)
        os.chdir(_project_root)

        # Determine total steps based on email
        total = 7 if send_email else 6
        if run_state:
            run_state.total_steps = total

        app_graph = build_graph(
            send_email=send_email,
            on_node_start=on_node_start,
            on_node_end=on_node_end,
        )

        initial_state = {"listing_url": listing_url}
        if email_to:
            initial_state["email_to"] = email_to

        langfuse_handler = None
        invoke_config = {}
        if _langfuse_enabled:
            langfuse_handler = LangfuseHandler(
                trace_name=f"appraisal-{run_id}",
                metadata={"run_id": run_id, "listing_url": listing_url},
            )
            invoke_config["callbacks"] = [langfuse_handler]

        result = app_graph.invoke(initial_state, config=invoke_config)

        # Build report for history/preview
        try:
            report = build_report(result)
            result["email_image_paths"] = [
                str(p) for p in report.get("email_image_paths", [])
            ]
            update_run(
                run_id,
                status="completed",
                state=result,
                report_html=report["html_body"],
                report_subject=report["subject"],
            )
        except Exception:
            update_run(run_id, status="completed", state=result)

        # Fetch cost and runtime from Langfuse (if enabled)
        langfuse_cost = None
        langfuse_latency = None
        langfuse_trace_url = None
        if _langfuse_enabled and langfuse_handler is not None:
            try:
                langfuse_handler.flush()
                langfuse_client = _get_langfuse_client()
                trace = None
                # Retry with backoff — Langfuse needs time to ingest the trace
                for delay in (3, 5, 10):
                    time.sleep(delay)
                    try:
                        trace = langfuse_client.api.trace.get(langfuse_handler.trace_id)
                        if trace.total_cost is not None:
                            break
                    except Exception:
                        continue
                if trace is None:
                    raise RuntimeError("Failed to fetch Langfuse trace after retries")
                langfuse_cost = trace.total_cost
                langfuse_latency = trace.latency
                langfuse_host = os.getenv("LANGFUSE_HOST", "")
                # For the UI link, use the external host (not internal Docker URL)
                external_host = langfuse_host.replace(
                    "http://langfuse:3000", "http://localhost:3002"
                )
                langfuse_trace_url = f"{external_host}/trace/{langfuse_handler.trace_id}"
                update_run(
                    run_id,
                    langfuse_trace_id=langfuse_handler.trace_id,
                    langfuse_total_cost=langfuse_cost,
                    langfuse_latency=langfuse_latency,
                    langfuse_trace_url=langfuse_trace_url,
                )
            except Exception:
                pass  # Langfuse fetch is best-effort

        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "pipeline_complete",
                "run_id": run_id,
                "cost": langfuse_cost,
                "duration": langfuse_latency,
            },
        )

    except Exception as e:
        error_msg = str(e)
        update_run(run_id, status="failed", error=error_msg)
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "error", "text": error_msg, "run_id": run_id},
        )

    finally:
        # Clean up thread-local
        _thread_local.run_id = None
        pipeline_mgr.finish_run(run_id)
        pipeline_mgr.cleanup_old_runs()
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "done", "run_id": run_id},
        )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

async def _queue_broadcaster():
    """Single background task that consumes the queue and broadcasts to all clients."""
    while True:
        try:
            msg = await asyncio.wait_for(pipeline_mgr.queue.get(), timeout=1.0)
            await pipeline_mgr.broadcast(msg)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except Exception:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan — create broadcast queue and start broadcaster."""
    pipeline_mgr.queue = asyncio.Queue()
    broadcaster = asyncio.create_task(_queue_broadcaster())
    yield
    # Cleanup on shutdown
    broadcaster.cancel()
    pipeline_mgr.reset()


app = FastAPI(
    title="Marketplace Appraiser",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for local Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AppraiseRequest(BaseModel):
    listing_url: str
    send_email: bool = False
    email_to: str = ""

    @field_validator("listing_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("listing_url is required")
        if not v.startswith(("http://", "https://")):
            raise ValueError("listing_url must start with http:// or https://")
        return v

    @field_validator("email_to")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("email_to must be a valid email address")
        return v


class AppraiseResponse(BaseModel):
    run_id: str
    status: str


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "running": pipeline_mgr.is_running,
        "active_runs": pipeline_mgr.active_run_ids,
    }


@app.post("/api/appraise", response_model=AppraiseResponse)
async def start_appraisal(req: AppraiseRequest):
    """Start a new appraisal pipeline run.

    Supports concurrent runs — each gets its own thread and log buffer.
    """
    email_to = req.email_to or os.getenv("EMAIL_TO", "") or os.getenv("GMAIL_USER", "")
    run_id = create_run(req.listing_url, send_email=req.send_email)

    total_steps = 7 if req.send_email else 6
    run_state = pipeline_mgr.start_run(run_id, total_steps)

    loop = asyncio.get_event_loop()
    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(req.listing_url, run_id, req.send_email, email_to,
              pipeline_mgr.queue, loop),
        daemon=True,
    )
    run_state.thread = thread
    thread.start()

    return AppraiseResponse(run_id=run_id, status="running")


@app.get("/api/status")
async def pipeline_status():
    """Get current pipeline status (all active runs)."""
    active = pipeline_mgr.active_run_ids
    runs_status = []
    for rid in active:
        rs = pipeline_mgr.get_run(rid)
        if rs:
            runs_status.append({
                "run_id": rid,
                "current_step": rs.current_step,
                "total_steps": rs.total_steps,
            })
    return {
        "is_running": len(active) > 0,
        "active_runs": runs_status,
        # Backward compat: report the most recent active run
        "run_id": active[-1] if active else None,
        "current_step": runs_status[-1]["current_step"] if runs_status else 0,
        "total_steps": runs_status[-1]["total_steps"] if runs_status else 7,
    }


@app.post("/api/reset")
async def reset_pipeline():
    """Force-reset all pipeline state."""
    pipeline_mgr.reset()
    # Notify connected clients
    for client in list(pipeline_mgr._clients):
        try:
            await client.send_json({
                "type": "status",
                "is_running": False,
                "run_id": None,
                "current_step": 0,
                "total_steps": 7,
            })
            await client.send_json({"type": "done"})
        except Exception:
            pass
    return {"status": "reset"}


@app.get("/api/runs")
async def get_runs(limit: int = 50):
    """List recent appraisal runs."""
    return list_runs(limit=limit)


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    """Get full details for a specific run."""
    record = get_run(run_id)
    if not record:
        return JSONResponse(status_code=404, content={"detail": "Run not found"})
    return record


@app.get("/api/runs/{run_id}/preview", response_class=HTMLResponse)
async def get_run_email_preview(run_id: str):
    """Get the email HTML preview for a run.

    Rewrites CID image references to base64 data URIs so images display
    in the browser preview (CID only works in email clients).
    """
    record = get_run(run_id)
    if not record:
        return HTMLResponse(
            content="<p>No preview available</p>", status_code=404,
        )
    html = record.get("report_html")
    if not html:
        return HTMLResponse(
            content="<p>No preview available</p>", status_code=404,
        )

    # Replace cid:listing_photo_N with base64 data URIs.
    # Use the run's saved email_image_paths (exact paths used for CIDs)
    # or fall back to image_paths.
    import base64
    import re as _re
    import mimetypes

    project_root = Path(__file__).parent.parent.parent
    state = record.get("state", {})
    email_image_paths = state.get("email_image_paths") or state.get("image_paths", [])

    # Find all CID references in the HTML
    cid_refs = _re.findall(r'src="cid:listing_photo_(\d+)"', html)
    for idx_str in cid_refs:
        idx = int(idx_str)
        if idx >= len(email_image_paths):
            continue
        img_path = Path(email_image_paths[idx])
        if not img_path.is_absolute():
            img_path = project_root / img_path
        if not img_path.exists():
            continue
        mime_type = mimetypes.guess_type(str(img_path))[0] or "image/jpeg"
        try:
            img_b64 = base64.b64encode(img_path.read_bytes()).decode()
            html = html.replace(
                f'src="cid:listing_photo_{idx}"',
                f'src="data:{mime_type};base64,{img_b64}"',
            )
        except OSError:
            pass

    return HTMLResponse(content=html)


@app.post("/api/runs/{run_id}/send")
async def send_run_email(run_id: str, email_to: str = ""):
    """Send (or re-send) the appraisal email for a completed run."""
    record = get_run(run_id)
    if not record:
        return JSONResponse(status_code=404, content={"detail": "Run not found"})

    if record.get("status") != "completed":
        return JSONResponse(
            status_code=400,
            content={"detail": f"Run is {record.get('status')}, not completed"},
        )

    report_html = record.get("report_html")
    if not report_html:
        return JSONResponse(
            status_code=400,
            content={"detail": "No report HTML available for this run"},
        )

    # Build plain text from state
    state = record.get("state", {})
    subject = record.get("report_subject", "Marketplace Appraisal")

    # Resolve recipient
    recipient = (
        email_to
        or os.getenv("EMAIL_TO", "")
        or os.getenv("GMAIL_USER", "")
    )
    if not recipient:
        return JSONResponse(
            status_code=400,
            content={"detail": "No email recipient configured"},
        )

    # Gather image paths from state
    image_paths = [
        Path(p) for p in state.get("image_paths", [])
        if Path(p).exists()
    ]

    # Use first 4 images as in the email
    email_image_paths = image_paths[:4]

    # Build a minimal plain text fallback
    item_name = state.get("item_name", "Unknown Item")
    price_assessment = state.get("price_assessment", "")
    plain_body = f"{item_name}\n\n{price_assessment}\n"

    success, error = send_report_email(
        subject=subject,
        html_body=report_html,
        plain_body=plain_body,
        email_image_paths=email_image_paths,
        email_to=recipient,
    )

    if success:
        return {"status": "sent", "email_to": recipient}
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to send: {error}"},
        )


# ---------------------------------------------------------------------------
# Feedback / RL endpoints
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    user_action: str  # "bought", "negotiated", "passed", "still_looking"
    final_price: Optional[float] = None
    satisfaction: Optional[int] = None  # 1-5
    price_accuracy: Optional[int] = None  # 1-5
    notes: str = ""


@app.post("/api/runs/{run_id}/feedback")
async def submit_feedback(run_id: str, req: FeedbackRequest):
    """Submit outcome feedback for a completed appraisal run."""
    from marketplace_appraiser.feedback import save_feedback

    result = save_feedback(
        run_id,
        user_action=req.user_action,
        final_price=req.final_price,
        satisfaction=req.satisfaction,
        price_accuracy=req.price_accuracy,
        notes=req.notes,
    )
    if not result:
        return JSONResponse(
            status_code=404, content={"detail": "Run not found"},
        )
    return result


@app.get("/api/runs/{run_id}/feedback")
async def get_run_feedback(run_id: str):
    """Get existing feedback for a run."""
    from marketplace_appraiser.feedback import get_feedback

    fb = get_feedback(run_id)
    if not fb:
        return JSONResponse(
            status_code=404, content={"detail": "No feedback for this run"},
        )
    return fb


@app.get("/api/feedback")
async def list_all_feedback():
    """List all feedback records (for RL training dashboard)."""
    from marketplace_appraiser.feedback import list_feedback
    return list_feedback()


@app.get("/api/feedback/training-data")
async def get_rl_training_data():
    """Get feature/action/reward tuples for RL model training."""
    from marketplace_appraiser.feedback import get_training_data
    data = get_training_data()
    return {"count": len(data), "data": data}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/progress")
async def websocket_progress(ws: WebSocket):
    """Stream real-time pipeline progress to connected clients.

    The actual queue consumption happens in _queue_broadcaster().
    This handler just keeps the connection alive and sends heartbeats.
    """
    await ws.accept()
    pipeline_mgr._clients.add(ws)

    try:
        # Send current status on connect
        active = pipeline_mgr.active_run_ids
        most_recent = active[-1] if active else None
        rs = pipeline_mgr.get_run(most_recent) if most_recent else None
        await ws.send_json({
            "type": "status",
            "is_running": len(active) > 0,
            "run_id": most_recent,
            "current_step": rs.current_step if rs else 0,
            "total_steps": rs.total_steps if rs else 7,
            "active_runs": active,
        })

        # Replay buffered messages so late-connecting clients get full history
        await pipeline_mgr.replay_buffer(ws)

        # Keep connection alive — messages are pushed by _queue_broadcaster()
        while True:
            try:
                # Wait for client messages (ping/pong or close)
                await asyncio.wait_for(ws.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                try:
                    await ws.send_json({"type": "heartbeat"})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        pipeline_mgr._clients.discard(ws)


# ---------------------------------------------------------------------------
# Serve static dashboard (Phase 2) — mount last so API routes take priority
# ---------------------------------------------------------------------------

_dashboard_dist = Path(__file__).parent.parent.parent / "dashboard" / "dist"
if _dashboard_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dashboard_dist), html=True))
