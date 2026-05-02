"""Avocet — CF planning benchmark integration API.

Wraps scripts/benchmark_plans.py and exposes it via the Avocet API.
Connection config (api_base) is read from label_tool.yaml under the
`plans_bench:` key (optional; falls back to localhost:8080).

All endpoints are registered on `router` (FastAPI APIRouter).
api.py includes this router with prefix="/api/plans-bench".
"""
from __future__ import annotations

import json
import logging
import subprocess as _subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_CONFIG_DIR: Path | None = None  # override in tests via set_config_dir()
_BENCH_RUNNING: bool = False
_bench_proc: Any = None

_BENCH_SCRIPT = _ROOT / "scripts" / "benchmark_plans.py"
_RESULTS_DIR  = _ROOT / "data" / "plans_bench_results"

router = APIRouter()

# ── Registered model shortcuts (mirrors benchmark_plans.MODEL_REGISTRY) ────────
# Kept here so the UI can list them without importing the script.

MODEL_REGISTRY: dict[str, str] = {
    "llama3.2-3b":  "Llama 3.2 3B Instruct (local via cf-text)",
    "llama3.2-1b":  "Llama 3.2 1B Instruct (local via cf-text)",
    "mistral-7b":   "Mistral 7B Instruct (local via cf-text)",
    "phi3-mini":    "Phi-3 Mini 3.8B (local via cf-text)",
    "qwen2.5-3b":   "Qwen 2.5 3B Instruct (local via cf-text)",
}

RUBRIC_LABELS: dict[str, str] = {
    "task_structure":  "Task structure (checkboxes + commits)",
    "tier_awareness":  "Tier awareness (Free/Paid/Premium/Ultra)",
    "privacy_pillar":  "Privacy pillar (local-first, no logging)",
    "safety_pillar":   "Safety pillar (human approval, reversibility)",
    "accessibility":   "Accessibility (ND/adaptive users)",
    "license_split":   "License awareness (MIT vs BSL)",
    "file_paths":      "File paths (plausible project paths)",
    "cf_conventions":  "CF conventions (conda, manage.sh, /Library/…)",
    "length_ok":       "Response length (200–2500 words)",
}


# ── Testability seam ───────────────────────────────────────────────────────────

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path


# ── Internal helpers ───────────────────────────────────────────────────────────

def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def _load_config() -> dict:
    f = _config_file()
    cforch_cfg: dict = {}
    bench_cfg: dict = {}
    if f.exists():
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            cforch_cfg = raw.get("cforch", {}) or {}
            bench_cfg  = raw.get("plans_bench", {}) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse plans_bench config %s: %s", f, exc)
    return {
        "coordinator_url": cforch_cfg.get("coordinator_url",
                           bench_cfg.get("coordinator_url", "http://10.1.10.71:7700")),
        "python_bin":      cforch_cfg.get("python_bin",
                           bench_cfg.get("python_bin", "/devl/miniconda3/envs/cf/bin/python")),
    }


def _results_file(run_id: str) -> Path:
    return _RESULTS_DIR / f"{run_id}.json"


# ── GET /models ────────────────────────────────────────────────────────────────

@router.get("/models")
def get_models() -> dict:
    """Return registered model shortcuts, live cf-orch catalog, and rubric labels."""
    cfg = _load_config()

    cforch_models: list[dict] = []
    try:
        resp = httpx.get(
            f"{cfg['coordinator_url']}/api/services/cf-text/catalog",
            timeout=5.0,
        )
        resp.raise_for_status()
        for model_id, entry in resp.json().items():
            if isinstance(entry, dict):
                cforch_models.append({
                    "id":          model_id,
                    "name":        model_id,
                    "vram_mb":     entry.get("vram_mb"),
                    "description": entry.get("description", ""),
                })
    except Exception as exc:
        logger.warning("Failed to fetch cf-orch catalog: %s", exc)

    return {
        "registry": [
            {"key": k, "description": v}
            for k, v in MODEL_REGISTRY.items()
        ],
        "cforch_models": cforch_models,
        "coordinator_url": cfg["coordinator_url"],
        "rubric_labels": RUBRIC_LABELS,
    }


# ── GET /run ───────────────────────────────────────────────────────────────────

@router.get("/run")
def run_plans_benchmark(
    models: str = Query(..., description="Comma-separated model IDs (registry keys or cf-orch model names)"),
    prompt_ids: str = Query("", description="Comma-separated prompt IDs to run (empty = all 10)"),
    use_cforch: bool = Query(True, description="Route inference through cf-orch coordinator"),
    api_base: str = Query("", description="Direct API base URL when not using cf-orch"),
    workers: int = Query(1, ge=1, le=8, description="Number of models to benchmark concurrently"),
) -> StreamingResponse:
    """Spawn benchmark_plans.py and stream stdout as SSE progress events.

    On successful completion emits a `type: result` event with parsed JSON
    and saves results to data/plans_bench_results/<run_id>.json.
    """
    global _BENCH_RUNNING, _bench_proc

    if _BENCH_RUNNING:
        raise HTTPException(409, "A planning benchmark is already running")

    cfg = _load_config()
    python_bin = cfg["python_bin"]
    coordinator_url = cfg["coordinator_url"]

    model_keys = [m.strip() for m in models.split(",") if m.strip()]
    if not model_keys:
        raise HTTPException(400, "At least one model key is required")

    run_id = datetime.now(tz=timezone.utc).strftime("plans_%Y-%m-%d_%H%M%S")
    output_path = _results_file(run_id)
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def generate():
        global _BENCH_RUNNING, _bench_proc

        if not _BENCH_SCRIPT.exists():
            yield f"data: {json.dumps({'type': 'error', 'message': f'benchmark_plans.py not found at {_BENCH_SCRIPT}'})}\n\n"
            return

        cmd = [python_bin, str(_BENCH_SCRIPT)]
        if len(model_keys) > 1:
            cmd.extend(["--compare"] + model_keys)
        else:
            cmd.extend(["--model", model_keys[0]])

        if use_cforch:
            cmd.extend(["--cforch", "--cforch-url", coordinator_url])
        elif api_base.strip():
            cmd.extend(["--api-base", api_base.strip()])

        cmd.extend(["--verbose", "--output", str(output_path)])
        if workers > 1:
            cmd.extend(["--workers", str(workers)])

        if prompt_ids.strip():
            cmd.extend(["--prompts"] + [p.strip() for p in prompt_ids.split(",") if p.strip()])

        _BENCH_RUNNING = True
        try:
            proc = _subprocess.Popen(
                cmd,
                stdout=_subprocess.PIPE,
                stderr=_subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(_ROOT),
            )
            _bench_proc = proc
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        yield f"data: {json.dumps({'type': 'progress', 'message': line})}\n\n"
                proc.wait()
                if proc.returncode == 0 and output_path.exists():
                    try:
                        results = json.loads(output_path.read_text(encoding="utf-8"))
                        yield f"data: {json.dumps({'type': 'result', 'run_id': run_id, 'results': results})}\n\n"
                    except Exception as exc:
                        logger.warning("Failed to read plans benchmark output: %s", exc)
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Process exited with code {proc.returncode}'})}\n\n"
            finally:
                _bench_proc = None
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        finally:
            _BENCH_RUNNING = False

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── GET /results ───────────────────────────────────────────────────────────────

@router.get("/results")
def list_results() -> list[dict]:
    """List past planning benchmark runs, newest first."""
    if not _RESULTS_DIR.exists():
        return []

    runs: list[dict] = []
    for f in sorted(_RESULTS_DIR.glob("plans_*.json"), reverse=True):
        run_id = f.stem
        try:
            data: dict = json.loads(f.read_text(encoding="utf-8"))
            model_keys = list(data.keys())
            # Average total_score across all models and prompts
            all_scores = [
                r["total_score"]
                for results in data.values()
                for r in results
                if not r.get("error")
            ]
            avg_score = round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0
        except Exception:
            model_keys = []
            avg_score = 0.0

        # Parse display date from run_id (plans_2026-04-27_143022)
        try:
            date_part = run_id.removeprefix("plans_")  # 2026-04-27_143022
            date, time = date_part.split("_")
            display_date = f"{date} {time[:2]}:{time[2:4]}"
        except Exception:
            display_date = run_id

        runs.append({
            "run_id":      run_id,
            "filename":    f.name,
            "date":        display_date,
            "models":      model_keys,
            "avg_score":   avg_score,
        })

    return runs


@router.get("/results/latest")
def get_latest_results() -> dict:
    """Return the most recent planning benchmark results dict."""
    if not _RESULTS_DIR.exists():
        raise HTTPException(404, "No benchmark results found")
    files = sorted(_RESULTS_DIR.glob("plans_*.json"))
    if not files:
        raise HTTPException(404, "No benchmark results found")
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Failed to read results: {exc}") from exc


@router.get("/results/{run_id}")
def get_results_by_run_id(run_id: str) -> dict:
    """Return planning benchmark results for a specific run."""
    if not run_id.startswith("plans_"):
        raise HTTPException(400, "Invalid run_id — expected plans_YYYY-MM-DD_HHMMSS")
    f = _results_file(run_id)
    if not f.exists():
        raise HTTPException(404, f"Results not found: {run_id}")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Failed to read results: {exc}") from exc


# ── POST /cancel ───────────────────────────────────────────────────────────────

@router.post("/cancel")
def cancel_plans_benchmark() -> dict:
    """Kill the running planning benchmark subprocess."""
    global _BENCH_RUNNING, _bench_proc

    if not _BENCH_RUNNING:
        raise HTTPException(404, "No planning benchmark is currently running")

    if _bench_proc is not None:
        try:
            _bench_proc.terminate()
        except Exception as exc:
            logger.warning("Failed to terminate plans benchmark: %s", exc)

    _BENCH_RUNNING = False
    _bench_proc = None
    return {"status": "cancelled"}
