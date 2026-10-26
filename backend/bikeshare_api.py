"""HW7 Part 4 UI backend: upload a trip CSV + pricing URL, run the ReAct agent, poll its timeline."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.bikeshare_agent import Defenses, run_bikeshare_agent
from src.bikeshare_tools import fetch_snapshot, save_snapshot

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "templates" / "bikeshare.html"
SNAPSHOT_DIR = ROOT / "reports" / "hw07" / "raw" / "pricing_snapshots"
MAX_CSV_BYTES = 5 * 1024 * 1024

router = APIRouter(tags=["HW7 bike-share agent"])
RUNS: dict[str, dict[str, Any]] = {}
MODEL_LOCK = threading.Lock()  # one local model run at a time


@router.get("/bikeshare", include_in_schema=False)
def bikeshare_page() -> FileResponse:
    """The single-page UI."""

    return FileResponse(PAGE)


def _worker(run_id: str, csv_bytes: bytes, pricing_url: str, defenses: Defenses, label: str) -> None:
    state = RUNS[run_id]
    try:
        with MODEL_LOCK:
            state["status"] = "running"
            snapshot = fetch_snapshot(pricing_url)
            save_snapshot(snapshot, SNAPSHOT_DIR / f"{snapshot.sha256[:16]}.json")
            result = run_bikeshare_agent(csv_bytes, pricing_url, defenses=defenses, snapshot=snapshot,
                                         scenario=label, on_event=state["timeline"].append,
                                         run_id=f"ui-{label}-{run_id}")
        state.update(status="done", result=result)
    except Exception as exc:  # report failures to the page instead of losing them in a thread
        state.update(status="error", error=f"{type(exc).__name__}: {exc}")


@router.post("/api/bikeshare/runs", status_code=202)
async def start_run(
    trips_csv: UploadFile = File(...),
    pricing_url: str = Form(...),
    label_untrusted: bool = Form(True),
    enforce_readonly: bool = Form(True),
) -> dict:
    """Start an agent run in the background and return its id for polling."""

    csv_bytes = await trips_csv.read()
    if not csv_bytes or len(csv_bytes) > MAX_CSV_BYTES:
        raise HTTPException(status_code=422, detail="CSV must be between 1 byte and 5 MB")
    if not pricing_url.startswith(("https://", "http://", "file://")):
        raise HTTPException(status_code=422, detail="pricing_url must be an http(s) or file URL")
    run_id = uuid.uuid4().hex[:8]
    label = Path(trips_csv.filename or "upload").stem.replace("bikeshare_", "")[:40] or "upload"
    RUNS[run_id] = {"status": "queued", "timeline": [], "result": None, "error": None,
                    "filename": trips_csv.filename, "pricing_url": pricing_url}
    defenses = Defenses(label_untrusted=label_untrusted, enforce_readonly=enforce_readonly)
    threading.Thread(target=_worker, args=(run_id, csv_bytes, pricing_url, defenses, label), daemon=True).start()
    return {"run_id": run_id}


@router.get("/api/bikeshare/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """Current status, the timeline so far, and the result once finished."""

    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, **state, "timeline": list(state["timeline"])}
