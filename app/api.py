"""Avocet — FastAPI REST layer.

JSONL read/write helpers and FastAPI app instance.
Endpoints and static file serving are added in subsequent tasks.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess as _subprocess
import yaml
from pathlib import Path

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

_ROOT = Path(__file__).parent.parent
_DATA_DIR: Path = _ROOT / "data"     # overridable in tests via set_data_dir()
_MODELS_DIR: Path = _ROOT / "models" # overridable in tests via set_models_dir()
_CONFIG_DIR: Path | None = None      # None = use real path

# Process registry for running jobs — used by cancel endpoints.
# Keys: "benchmark" | "finetune". Values: the live Popen object.
_running_procs: dict = {}
_cancelled_jobs: set = set()


def set_data_dir(path: Path) -> None:
    """Override data directory — used by tests."""
    global _DATA_DIR
    _DATA_DIR = path


def _best_cuda_device() -> str:
    """Return the index of the GPU with the most free VRAM as a string.

    Uses nvidia-smi so it works in the job-seeker env (no torch). Returns ""
    if nvidia-smi is unavailable or no GPUs are found. Restricting the
    training subprocess to a single GPU via CUDA_VISIBLE_DEVICES prevents
    PyTorch DataParallel from replicating the model across all GPUs, which
    would OOM the GPU with less headroom.
    """
    try:
        out = _subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.free",
             "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
        best_idx, best_free = "", 0
        for line in out.strip().splitlines():
            parts = line.strip().split(", ")
            if len(parts) == 2:
                idx, free = parts[0].strip(), int(parts[1].strip())
                if free > best_free:
                    best_free, best_idx = free, idx
        return best_idx
    except Exception:
        return ""


def set_models_dir(path: Path) -> None:
    """Override models directory — used by tests."""
    global _MODELS_DIR
    _MODELS_DIR = path


def set_config_dir(path: Path | None) -> None:
    """Override config directory — used by tests."""
    global _CONFIG_DIR
    _CONFIG_DIR = path


def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def reset_last_action() -> None:
    """Reset undo state — used by tests."""
    global _last_action
    _last_action = None


def _queue_file() -> Path:
    return _DATA_DIR / "email_label_queue.jsonl"


def _score_file() -> Path:
    return _DATA_DIR / "email_score.jsonl"


def _discarded_file() -> Path:
    return _DATA_DIR / "discarded.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    path.write_text(text + "\n" if records else "", encoding="utf-8")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _item_id(item: dict) -> str:
    """Stable content-hash ID — matches label_tool.py _entry_key dedup logic."""
    key = (item.get("subject", "") + (item.get("body", "") or "")[:100])
    return hashlib.md5(key.encode("utf-8", errors="replace")).hexdigest()


def _normalize(item: dict) -> dict:
    """Normalize JSONL item to the Vue frontend schema.

    label_tool.py stores: subject, body, from_addr, date, account (no id).
    The Vue app expects: id, subject, body, from, date, source.
    Both old (from_addr/account) and new (from/source) field names are handled.
    """
    return {
        "id":      item.get("id") or _item_id(item),
        "subject": item.get("subject", ""),
        "body":    item.get("body", ""),
        "from":    item.get("from") or item.get("from_addr", ""),
        "date":    item.get("date", ""),
        "source":  item.get("source") or item.get("account", ""),
    }


app = FastAPI(title="Avocet API")

from app.sft import router as sft_router
app.include_router(sft_router, prefix="/api/sft")

from app.models import router as models_router
app.include_router(models_router, prefix="/api/models")

# In-memory last-action store (single user, local tool — in-memory is fine)
_last_action: dict | None = None


@app.get("/api/queue")
def get_queue(limit: int = Query(default=10, ge=1, le=50)):
    items = _read_jsonl(_queue_file())
    return {"items": [_normalize(x) for x in items[:limit]], "total": len(items)}


class LabelRequest(BaseModel):
    id: str
    label: str


@app.post("/api/label")
def post_label(req: LabelRequest):
    global _last_action
    items = _read_jsonl(_queue_file())
    match = next((x for x in items if _normalize(x)["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    record = {**match, "label": req.label,
              "labeled_at": datetime.now(timezone.utc).isoformat()}
    _append_jsonl(_score_file(), record)
    _write_jsonl(_queue_file(), [x for x in items if _normalize(x)["id"] != req.id])
    _last_action = {"type": "label", "item": match, "label": req.label}
    return {"ok": True}


class SkipRequest(BaseModel):
    id: str


@app.post("/api/skip")
def post_skip(req: SkipRequest):
    global _last_action
    items = _read_jsonl(_queue_file())
    match = next((x for x in items if _normalize(x)["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    reordered = [x for x in items if _normalize(x)["id"] != req.id] + [match]
    _write_jsonl(_queue_file(), reordered)
    _last_action = {"type": "skip", "item": match}
    return {"ok": True}


class DiscardRequest(BaseModel):
    id: str


@app.post("/api/discard")
def post_discard(req: DiscardRequest):
    global _last_action
    items = _read_jsonl(_queue_file())
    match = next((x for x in items if _normalize(x)["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    record = {**match, "label": "__discarded__",
              "discarded_at": datetime.now(timezone.utc).isoformat()}
    _append_jsonl(_discarded_file(), record)
    _write_jsonl(_queue_file(), [x for x in items if _normalize(x)["id"] != req.id])
    _last_action = {"type": "discard", "item": match}
    return {"ok": True}


@app.delete("/api/label/undo")
def delete_undo():
    global _last_action
    if not _last_action:
        raise HTTPException(404, "No action to undo")
    action = _last_action
    item = action["item"]   # always the original clean queue item

    # Perform file operations FIRST — only clear _last_action on success
    if action["type"] == "label":
        records = _read_jsonl(_score_file())
        if not records:
            raise HTTPException(409, "Score file is empty — cannot undo label")
        _write_jsonl(_score_file(), records[:-1])
        items = _read_jsonl(_queue_file())
        _write_jsonl(_queue_file(), [item] + items)
    elif action["type"] == "discard":
        records = _read_jsonl(_discarded_file())
        if not records:
            raise HTTPException(409, "Discarded file is empty — cannot undo discard")
        _write_jsonl(_discarded_file(), records[:-1])
        items = _read_jsonl(_queue_file())
        _write_jsonl(_queue_file(), [item] + items)
    elif action["type"] == "skip":
        items = _read_jsonl(_queue_file())
        item_id = _normalize(item)["id"]
        items = [item] + [x for x in items if _normalize(x)["id"] != item_id]
        _write_jsonl(_queue_file(), items)

    # Clear AFTER all file operations succeed
    _last_action = None
    return {"undone": {"type": action["type"], "item": _normalize(item)}}


# Label metadata — 10 labels matching label_tool.py
_LABEL_META = [
    {"name": "interview_scheduled", "emoji": "\U0001f4c5",  "color": "#4CAF50", "key": "1"},
    {"name": "offer_received",      "emoji": "\U0001f389",  "color": "#2196F3", "key": "2"},
    {"name": "rejected",            "emoji": "\u274c",      "color": "#F44336", "key": "3"},
    {"name": "positive_response",   "emoji": "\U0001f44d",  "color": "#FF9800", "key": "4"},
    {"name": "survey_received",     "emoji": "\U0001f4cb",  "color": "#9C27B0", "key": "5"},
    {"name": "neutral",             "emoji": "\u2b1c",      "color": "#607D8B", "key": "6"},
    {"name": "event_rescheduled",   "emoji": "\U0001f504",  "color": "#FF5722", "key": "7"},
    {"name": "digest",              "emoji": "\U0001f4f0",  "color": "#00BCD4", "key": "8"},
    {"name": "new_lead",            "emoji": "\U0001f91d",  "color": "#009688", "key": "9"},
    {"name": "hired",               "emoji": "\U0001f38a",  "color": "#FFC107", "key": "h"},
]


@app.get("/api/config/labels")
def get_labels():
    return _LABEL_META


@app.get("/api/config")
def get_config():
    f = _config_file()
    if not f.exists():
        return {"accounts": [], "max_per_account": 500}
    raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return {"accounts": raw.get("accounts", []), "max_per_account": raw.get("max_per_account", 500)}


class ConfigPayload(BaseModel):
    accounts: list[dict]
    max_per_account: int = 500


@app.post("/api/config")
def post_config(payload: ConfigPayload):
    f = _config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(yaml.dump(payload.model_dump(), allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    tmp.rename(f)
    return {"ok": True}


@app.get("/api/stats")
def get_stats():
    records = _read_jsonl(_score_file())
    counts: dict[str, int] = {}
    for r in records:
        lbl = r.get("label", "")
        if lbl:
            counts[lbl] = counts.get(lbl, 0) + 1
    return {
        "total": len(records),
        "counts": counts,
        "score_file_bytes": _score_file().stat().st_size if _score_file().exists() else 0,
    }


@app.get("/api/stats/download")
def download_stats():
    from fastapi.responses import FileResponse
    if not _score_file().exists():
        raise HTTPException(404, "No score file")
    return FileResponse(
        str(_score_file()),
        filename="email_score.jsonl",
        media_type="application/jsonlines",
        headers={"Content-Disposition": 'attachment; filename="email_score.jsonl"'},
    )


class AccountTestRequest(BaseModel):
    account: dict


@app.post("/api/accounts/test")
def test_account(req: AccountTestRequest):
    from app.imap_fetch import test_connection
    ok, message, count = test_connection(req.account)
    return {"ok": ok, "message": message, "count": count}


from fastapi.responses import StreamingResponse


# ---------------------------------------------------------------------------
# Benchmark endpoints
# ---------------------------------------------------------------------------

@app.get("/api/benchmark/results")
def get_benchmark_results():
    """Return the most recently saved benchmark results, or an empty envelope."""
    path = _DATA_DIR / "benchmark_results.json"
    if not path.exists():
        return {"models": {}, "sample_count": 0, "timestamp": None}
    return json.loads(path.read_text())


@app.get("/api/benchmark/run")
def run_benchmark(include_slow: bool = False):
    """Spawn the benchmark script and stream stdout as SSE progress events."""
    python_bin = "/devl/miniconda3/envs/job-seeker-classifiers/bin/python"
    script = str(_ROOT / "scripts" / "benchmark_classifier.py")
    cmd = [python_bin, script, "--score", "--save"]
    if include_slow:
        cmd.append("--include-slow")

    def generate():
        try:
            proc = _subprocess.Popen(
                cmd,
                stdout=_subprocess.PIPE,
                stderr=_subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(_ROOT),
            )
            _running_procs["benchmark"] = proc
            _cancelled_jobs.discard("benchmark")  # clear any stale flag from a prior run
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        yield f"data: {json.dumps({'type': 'progress', 'message': line})}\n\n"
                proc.wait()
                if proc.returncode == 0:
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                elif "benchmark" in _cancelled_jobs:
                    _cancelled_jobs.discard("benchmark")
                    yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Process exited with code {proc.returncode}'})}\n\n"
            finally:
                _running_procs.pop("benchmark", None)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Finetune endpoints
# ---------------------------------------------------------------------------

@app.get("/api/finetune/status")
def get_finetune_status():
    """Scan models/ for training_info.json files. Returns [] if none exist."""
    models_dir = _MODELS_DIR
    if not models_dir.exists():
        return []
    results = []
    for sub in models_dir.iterdir():
        if not sub.is_dir():
            continue
        info_path = sub / "training_info.json"
        if not info_path.exists():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            results.append(info)
        except Exception:
            pass
    return results


@app.get("/api/finetune/run")
def run_finetune_endpoint(
    model: str = "deberta-small",
    epochs: int = 5,
    score: list[str] = Query(default=[]),
):
    """Spawn finetune_classifier.py and stream stdout as SSE progress events."""
    python_bin = "/devl/miniconda3/envs/job-seeker-classifiers/bin/python"
    script = str(_ROOT / "scripts" / "finetune_classifier.py")
    cmd = [python_bin, script, "--model", model, "--epochs", str(epochs)]
    data_root = _DATA_DIR.resolve()
    for score_file in score:
        resolved = (_DATA_DIR / score_file).resolve()
        if not str(resolved).startswith(str(data_root)):
            raise HTTPException(400, f"Invalid score path: {score_file!r}")
        cmd.extend(["--score", str(resolved)])

    # Pick the GPU with the most free VRAM. Setting CUDA_VISIBLE_DEVICES to a
    # single device prevents DataParallel from replicating the model across all
    # GPUs, which would force a full copy onto the more memory-constrained device.
    proc_env = {**os.environ, "PYTORCH_ALLOC_CONF": "expandable_segments:True"}
    best_gpu = _best_cuda_device()
    if best_gpu:
        proc_env["CUDA_VISIBLE_DEVICES"] = best_gpu

    gpu_note = f"GPU {best_gpu}" if best_gpu else "CPU (no GPU found)"

    def generate():
        yield f"data: {json.dumps({'type': 'progress', 'message': f'[api] Using {gpu_note} (most free VRAM)'})}\n\n"
        try:
            proc = _subprocess.Popen(
                cmd,
                stdout=_subprocess.PIPE,
                stderr=_subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(_ROOT),
                env=proc_env,
            )
            _running_procs["finetune"] = proc
            _cancelled_jobs.discard("finetune")  # clear any stale flag from a prior run
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        yield f"data: {json.dumps({'type': 'progress', 'message': line})}\n\n"
                proc.wait()
                if proc.returncode == 0:
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                elif "finetune" in _cancelled_jobs:
                    _cancelled_jobs.discard("finetune")
                    yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Process exited with code {proc.returncode}'})}\n\n"
            finally:
                _running_procs.pop("finetune", None)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/benchmark/cancel")
def cancel_benchmark():
    """Kill the running benchmark subprocess. 404 if none is running."""
    proc = _running_procs.get("benchmark")
    if proc is None:
        raise HTTPException(404, "No benchmark is running")
    _cancelled_jobs.add("benchmark")
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except _subprocess.TimeoutExpired:
        proc.kill()
    return {"status": "cancelled"}


@app.post("/api/finetune/cancel")
def cancel_finetune():
    """Kill the running fine-tune subprocess. 404 if none is running."""
    proc = _running_procs.get("finetune")
    if proc is None:
        raise HTTPException(404, "No finetune is running")
    _cancelled_jobs.add("finetune")
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except _subprocess.TimeoutExpired:
        proc.kill()
    return {"status": "cancelled"}


@app.get("/api/fetch/stream")
def fetch_stream(
    accounts: str = Query(default=""),
    days_back: int = Query(default=90, ge=1, le=365),
    limit: int = Query(default=150, ge=1, le=1000),
    mode: str = Query(default="wide"),
):
    from app.imap_fetch import fetch_account_stream

    selected_names = {n.strip() for n in accounts.split(",") if n.strip()}
    config = get_config()  # reuse existing endpoint logic
    selected = [a for a in config["accounts"] if a.get("name") in selected_names]

    def generate():
        known_keys = {_item_id(x) for x in _read_jsonl(_queue_file())}
        total_added = 0

        for acc in selected:
            try:
                batch_emails: list[dict] = []
                for event in fetch_account_stream(acc, days_back, limit, known_keys):
                    if event["type"] == "done":
                        batch_emails = event.pop("emails", [])
                        total_added += event["added"]
                    yield f"data: {json.dumps(event)}\n\n"
                # Write new emails to queue after each account
                if batch_emails:
                    existing = _read_jsonl(_queue_file())
                    _write_jsonl(_queue_file(), existing + batch_emails)
            except Exception as exc:
                error_event = {"type": "error", "account": acc.get("name", "?"),
                               "message": str(exc)}
                yield f"data: {json.dumps(error_event)}\n\n"

        queue_size = len(_read_jsonl(_queue_file()))
        complete = {"type": "complete", "total_added": total_added, "queue_size": queue_size}
        yield f"data: {json.dumps(complete)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Static SPA — MUST be last (catches all unmatched paths)
_DIST = _ROOT / "web" / "dist"
if _DIST.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Serve index.html with no-cache so browsers always fetch fresh HTML after rebuilds.
    # Hashed assets (/assets/index-abc123.js) can be cached forever — they change names
    # when content changes (standard Vite cache-busting strategy).
    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}

    @app.get("/")
    def get_spa_root():
        return FileResponse(str(_DIST / "index.html"), headers=_NO_CACHE)

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="spa")
