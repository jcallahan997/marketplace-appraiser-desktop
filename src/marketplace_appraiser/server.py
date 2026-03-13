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
from pydantic import BaseModel

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
# WebSocket stdout capture
# ---------------------------------------------------------------------------

# Step pattern that nodes print: "STEP N: ..."
_STEP_PATTERN = re.compile(r"^=+\nSTEP (\d+):|^STEP (\d+):")


class WebSocketWriter(io.TextIOBase):
    """Replaces sys.stdout to capture prints AND broadcast to WebSocket clients.

    Writes go to both the original stdout and an asyncio.Queue bridge.
    The Queue is consumed by the WebSocket endpoint.
    """

    def __init__(self, original_stdout, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._original = original_stdout
        self._queue = queue
        self._loop = loop

    def write(self, text: str) -> int:
        if text and text.strip():
            self._original.write(text)
            # Non-blocking put into the async queue from the pipeline thread
            try:
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait,
                    {"type": "stdout", "text": text.rstrip()},
                )
            except RuntimeError:
                pass  # loop closed
        elif text:
            self._original.write(text)  # preserve blank lines
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
# Global state for the running pipeline
# ---------------------------------------------------------------------------

class PipelineManager:
    """Manages the running pipeline and its WebSocket broadcast queue."""

    def __init__(self):
        self.queue: Optional[asyncio.Queue] = None
        self.current_run_id: Optional[str] = None
        self.current_step: int = 0
        self.total_steps: int = 7
        self.is_running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._cancel_flag: bool = False
        self._clients: set[WebSocket] = set()

    def reset(self):
        self.current_run_id = None
        self.current_step = 0
        self.is_running = False
        self._thread = None
        self._cancel_flag = False

    async def broadcast(self, message: dict):
        """Send a message to all connected WebSocket clients."""
        dead = set()
        for ws in self._clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self._clients -= dead


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

    Captures stdout, emits node start/end events, and saves results to history.
    """
    original_stdout = sys.stdout

    # Install the stdout interceptor
    writer = WebSocketWriter(original_stdout, queue, loop)
    sys.stdout = writer

    def on_node_start(node_name: str, step_num: int):
        pipeline_mgr.current_step = step_num
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "step_start",
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
                "node": node_name,
                "step": step_num,
                "label": STEP_LABELS.get(node_name, node_name),
            },
        )

    try:
        # Ensure output directory exists
        Path("output/images").mkdir(parents=True, exist_ok=True)

        # Determine total steps based on email
        total = 7 if send_email else 6
        pipeline_mgr.total_steps = total

        app_graph = build_graph(
            send_email=send_email,
            on_node_start=on_node_start,
            on_node_end=on_node_end,
        )

        initial_state = {"listing_url": listing_url}
        if email_to:
            initial_state["email_to"] = email_to

        result = app_graph.invoke(initial_state)

        # Build report for history/preview (even if email was already sent)
        try:
            report = build_report(result)
            update_run(
                run_id,
                status="completed",
                state=result,
                report_html=report["html_body"],
                report_subject=report["subject"],
            )
        except Exception:
            update_run(run_id, status="completed", state=result)

        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "pipeline_complete", "run_id": run_id},
        )

    except Exception as e:
        error_msg = str(e)
        update_run(run_id, status="failed", error=error_msg)
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "error", "text": error_msg, "run_id": run_id},
        )

    finally:
        sys.stdout = original_stdout
        pipeline_mgr.is_running = False
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "done"},
        )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan — create broadcast queue."""
    pipeline_mgr.queue = asyncio.Queue()
    yield
    # Cleanup on shutdown
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


class AppraiseResponse(BaseModel):
    run_id: str
    status: str


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "running": pipeline_mgr.is_running}


@app.post("/api/appraise", response_model=AppraiseResponse)
async def start_appraisal(req: AppraiseRequest):
    """Start a new appraisal pipeline run."""
    if pipeline_mgr.is_running:
        return JSONResponse(
            status_code=409,
            content={"detail": "A pipeline is already running."},
        )

    email_to = req.email_to or os.getenv("EMAIL_TO", "") or os.getenv("GMAIL_USER", "")
    run_id = create_run(req.listing_url, send_email=req.send_email)

    pipeline_mgr.is_running = True
    pipeline_mgr.current_run_id = run_id
    pipeline_mgr.current_step = 0

    # Fresh queue for this run
    pipeline_mgr.queue = asyncio.Queue()

    loop = asyncio.get_event_loop()
    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(req.listing_url, run_id, req.send_email, email_to,
              pipeline_mgr.queue, loop),
        daemon=True,
    )
    pipeline_mgr._thread = thread
    thread.start()

    return AppraiseResponse(run_id=run_id, status="running")


@app.get("/api/status")
async def pipeline_status():
    """Get current pipeline status."""
    return {
        "is_running": pipeline_mgr.is_running,
        "run_id": pipeline_mgr.current_run_id,
        "current_step": pipeline_mgr.current_step,
        "total_steps": pipeline_mgr.total_steps,
    }


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
    """Get the email HTML preview for a run."""
    html = get_run_preview(run_id)
    if not html:
        return HTMLResponse(
            content="<p>No preview available</p>", status_code=404,
        )
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
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/progress")
async def websocket_progress(ws: WebSocket):
    """Stream real-time pipeline progress to connected clients."""
    await ws.accept()
    pipeline_mgr._clients.add(ws)

    try:
        # Send current status on connect
        await ws.send_json({
            "type": "status",
            "is_running": pipeline_mgr.is_running,
            "run_id": pipeline_mgr.current_run_id,
            "current_step": pipeline_mgr.current_step,
            "total_steps": pipeline_mgr.total_steps,
        })

        # Consume queue messages and broadcast
        while True:
            try:
                # Wait for messages from the pipeline thread
                msg = await asyncio.wait_for(
                    pipeline_mgr.queue.get(), timeout=1.0,
                )
                # Broadcast to ALL clients
                await pipeline_mgr.broadcast(msg)

                if msg.get("type") == "done":
                    break
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                try:
                    await ws.send_json({"type": "heartbeat"})
                except Exception:
                    break
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    finally:
        pipeline_mgr._clients.discard(ws)


# ---------------------------------------------------------------------------
# Serve static dashboard (Phase 2) — mount last so API routes take priority
# ---------------------------------------------------------------------------

_dashboard_dist = Path(__file__).parent.parent.parent / "dashboard" / "dist"
if _dashboard_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dashboard_dist), html=True))
