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

from app.data.label import router as label_router
app.include_router(label_router, prefix="/api")

from app.sft import router as sft_router
app.include_router(sft_router, prefix="/api/sft")

from app.models import router as models_router
import app.models as _models_module
app.include_router(models_router, prefix="/api/models")

from app.cforch import router as cforch_router
app.include_router(cforch_router, prefix="/api/cforch")

from app.imitate import router as imitate_router
app.include_router(imitate_router, prefix="/api/imitate")

from app.style import router as style_router
app.include_router(style_router, prefix="/api/style")

from app.data.fetch import router as fetch_router
app.include_router(fetch_router, prefix="/api")


from fastapi.responses import StreamingResponse


# ---------------------------------------------------------------------------
# Benchmark endpoints
# ---------------------------------------------------------------------------

@app.get("/api/benchmark/models")
def get_benchmark_models() -> dict:
    """Return installed models grouped by adapter_type category."""
    models_dir: Path = _models_module._MODELS_DIR
    categories: dict[str, list[dict]] = {
        "ZeroShotAdapter": [],
        "RerankerAdapter": [],
        "GenerationAdapter": [],
        "Unknown": [],
    }
    if models_dir.exists():
        for sub in models_dir.iterdir():
            if not sub.is_dir():
                continue
            info_path = sub / "model_info.json"
            adapter_type = "Unknown"
            repo_id: str | None = None
            if info_path.exists():
                try:
                    info = json.loads(info_path.read_text(encoding="utf-8"))
                    adapter_type = info.get("adapter_type") or info.get("adapter_recommendation") or "Unknown"
                    repo_id = info.get("repo_id")
                except Exception:
                    pass
            bucket = adapter_type if adapter_type in categories else "Unknown"
            entry: dict = {"name": sub.name, "repo_id": repo_id, "adapter_type": adapter_type}
            categories[bucket].append(entry)
    return {"categories": categories}


@app.get("/api/benchmark/results")
def get_benchmark_results():
    """Return the most recently saved benchmark results, or an empty envelope."""
    path = _DATA_DIR / "benchmark_results.json"
    if not path.exists():
        return {"models": {}, "sample_count": 0, "timestamp": None}
    return json.loads(path.read_text())


@app.get("/api/benchmark/run")
def run_benchmark(include_slow: bool = False, model_names: str = ""):
    """Spawn the benchmark script and stream stdout as SSE progress events."""
    python_bin = "/devl/miniconda3/envs/job-seeker-classifiers/bin/python"
    script = str(_ROOT / "scripts" / "benchmark_classifier.py")
    cmd = [python_bin, script, "--score", "--save"]
    if include_slow:
        cmd.append("--include-slow")
    if model_names:
        names = [n.strip() for n in model_names.split(",") if n.strip()]
        if names:
            cmd.extend(["--models"] + names)

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
