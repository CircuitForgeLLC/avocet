"""Avocet — Writing style benchmark integration API.

Wraps scripts/benchmark_style.py and exposes it via the Avocet API.
Connection config (coordinator_url, ollama_url, python_bin) is read
from label_tool.yaml under the `cforch:` key — the same block used
by cforch.py, so no new config section is needed.

All endpoints are registered on `router` (a FastAPI APIRouter).
api.py includes this router with prefix="/api/style".

Module-level globals (_BENCH_RUNNING, _bench_proc) follow the same
testability pattern as cforch.py.
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
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_CONFIG_DIR: Path | None = None   # override in tests via set_config_dir()
_BENCH_RUNNING: bool = False
_bench_proc: Any = None

_BENCH_SCRIPT = _ROOT / "scripts" / "benchmark_style.py"
_RESULTS_DIR  = _ROOT / "benchmark_results"

router = APIRouter()


# ── Testability seams ──────────────────────────────────────────────────────────

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path


# ── Internal helpers ───────────────────────────────────────────────────────────

def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def _load_config() -> dict:
    """Read label_tool.yaml cforch section for coordinator/ollama/python config."""
    f = _config_file()
    file_cfg: dict = {}
    if f.exists():
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            file_cfg = raw.get("cforch", {}) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse style config %s: %s", f, exc)
    return {
        "coordinator_url": file_cfg.get("coordinator_url", "http://10.1.10.71:7700"),
        "ollama_url":      file_cfg.get("ollama_url",      "http://localhost:11434"),
        "python_bin":      file_cfg.get("python_bin",      "/devl/miniconda3/envs/cf/bin/python"),
    }


# ── GET /models ────────────────────────────────────────────────────────────────

@router.get("/models")
def get_models() -> dict:
    """Return available models grouped by source.

    - ollama: fetched live from /api/tags (includes any models downloaded
      via the Models view — automatically in sync)
    - cf_text: fetched from cf-orch catalog endpoint (requires node profile
      entry + coordinator restart when new GGUFs are added)
    """
    cfg = _load_config()

    # Ollama models — live query so newly downloaded models appear immediately
    ollama_models: list[dict] = []
    try:
        resp = httpx.get(f"{cfg['ollama_url']}/api/tags", timeout=5.0)
        resp.raise_for_status()
        for m in resp.json().get("models", []):
            name = m.get("name", "")
            if name:
                size_bytes = m.get("size", 0)
                ollama_models.append({
                    "id":      name,
                    "name":    name,
                    "source":  "ollama",
                    "size_mb": round(size_bytes / (1024 * 1024)) if size_bytes else None,
                    "vram_mb": None,
                })
    except Exception as exc:
        logger.warning("Failed to fetch ollama models: %s", exc)

    # cf-text catalog — fetched from cf-orch coordinator
    cftext_models: list[dict] = []
    try:
        resp = httpx.get(
            f"{cfg['coordinator_url']}/api/services/cf-text/catalog",
            timeout=5.0,
        )
        resp.raise_for_status()
        for model_id, entry in resp.json().items():
            if isinstance(entry, dict):
                cftext_models.append({
                    "id":          model_id,
                    "name":        model_id,
                    "source":      "cf-text",
                    "vram_mb":     entry.get("vram_mb"),
                    "description": entry.get("description", ""),
                })
    except Exception as exc:
        logger.warning("Failed to fetch cf-text catalog: %s", exc)

    return {"ollama": ollama_models, "cf_text": cftext_models}


# ── GET /run ───────────────────────────────────────────────────────────────────

@router.get("/run")
def run_style_benchmark(
    models: str = Query("", description="Comma-separated model IDs (empty = all)"),
    use_cforch: bool = Query(False),
    max_vram: int = Query(7200, description="Max VRAM MB for cf-orch OOM filter"),
    include_large: bool = Query(False, description="Include large (30B+) ollama models"),
    workers: int = Query(1, description="Parallel workers — run N models simultaneously"),
) -> StreamingResponse:
    """Spawn benchmark_style.py and stream stdout as SSE progress events.

    On successful completion, emits a final `type: result` event containing
    the parsed JSON from the newest style_*.json file.
    """
    global _BENCH_RUNNING, _bench_proc

    if _BENCH_RUNNING:
        raise HTTPException(409, "A writing style benchmark is already running")

    cfg = _load_config()
    python_bin = cfg["python_bin"]

    def generate():
        global _BENCH_RUNNING, _bench_proc

        if not _BENCH_SCRIPT.exists():
            yield f"data: {json.dumps({'type': 'error', 'message': f'benchmark_style.py not found at {_BENCH_SCRIPT}'})}\n\n"
            return

        cmd = [python_bin, str(_BENCH_SCRIPT), "run"]

        if models:
            cmd.extend(["--models", ",".join(m.strip() for m in models.split(",") if m.strip())])
        if use_cforch:
            cmd.extend(["--cforch", "--cforch-url", cfg["coordinator_url"],
                        "--max-vram", str(max_vram)])
        if include_large:
            cmd.append("--include-large")
        if workers > 1:
            cmd.extend(["--workers", str(workers)])

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
                if proc.returncode == 0:
                    result_files = sorted(_RESULTS_DIR.glob("style_*.json"))
                    if result_files:
                        try:
                            results = json.loads(result_files[-1].read_text(encoding="utf-8"))
                            yield f"data: {json.dumps({'type': 'result', 'results': results, 'filename': result_files[-1].name})}\n\n"
                        except Exception as exc:
                            logger.warning("Failed to read style results: %s", exc)
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
    """List past writing style benchmark runs, newest first.

    Returns lightweight summaries (date, model count, top score).
    Use /results/{filename} to fetch full model-level detail.
    """
    if not _RESULTS_DIR.exists():
        return []

    runs: list[dict] = []
    for f in sorted(_RESULTS_DIR.glob("style_*.json"), reverse=True):
        stem = f.stem  # style_2026-04-22_1502
        date_str = stem.removeprefix("style_")  # 2026-04-22_1502
        try:
            date_part, time_part = date_str.split("_")
            display_date = f"{date_part} {time_part[:2]}:{time_part[2:]}"
        except Exception:
            display_date = date_str

        try:
            results = json.loads(f.read_text(encoding="utf-8"))
            top_score = max((r.get("avg_score", 0) for r in results), default=0)
            model_count = len(results)
        except Exception:
            top_score = 0
            model_count = 0

        runs.append({
            "filename":    f.name,
            "date":        display_date,
            "model_count": model_count,
            "top_score":   round(top_score, 1),
        })

    return runs


@router.get("/results/latest")
def get_latest_results() -> list[dict]:
    """Return the latest writing style benchmark result list."""
    if not _RESULTS_DIR.exists():
        raise HTTPException(404, "No benchmark results found")
    files = sorted(_RESULTS_DIR.glob("style_*.json"))
    if not files:
        raise HTTPException(404, "No benchmark results found")
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Failed to read results: {exc}") from exc


@router.get("/results/{filename}")
def get_results_by_filename(filename: str) -> list[dict]:
    """Return writing style benchmark results for a specific run file."""
    if not filename.startswith("style_") or not filename.endswith(".json"):
        raise HTTPException(400, "Invalid filename — expected style_*.json")
    f = _RESULTS_DIR / filename
    if not f.exists():
        raise HTTPException(404, f"Results file not found: {filename}")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Failed to read results: {exc}") from exc


# ── POST /send-to-corrections ──────────────────────────────────────────────────

class SendToCorrectionsRequest(BaseModel):
    filename: str   # style_YYYY-MM-DD_HHMM.json — the source run file
    model_ids: list[str] = []  # empty = all models in the run


@router.post("/send-to-corrections")
def send_to_corrections(req: SendToCorrectionsRequest) -> dict:
    """Push writing style benchmark outputs into the SFT corrections queue.

    Each prompt_result from the selected models becomes one SFT candidate
    with status='needs_review'. Duplicates are skipped via the 'id' field
    (hash of model_id + tag).
    """
    if not req.filename.startswith("style_") or not req.filename.endswith(".json"):
        raise HTTPException(400, "Invalid filename")

    src = _RESULTS_DIR / req.filename
    if not src.exists():
        raise HTTPException(404, f"Results file not found: {req.filename}")

    try:
        run_results: list[dict] = json.loads(src.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Failed to read results: {exc}") from exc

    # Resolve sft_candidates.jsonl path (same logic as sft.py)
    sft_data_dir = _ROOT / "data"
    sft_file = sft_data_dir / "sft_candidates.jsonl"

    # Load existing IDs to deduplicate
    existing_ids: set[str] = set()
    if sft_file.exists():
        for line in sft_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    existing_ids.add(json.loads(line)["id"])
                except Exception:
                    pass

    run_id = req.filename.removesuffix(".json")  # style_2026-04-22_1502
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    new_candidates: list[dict] = []
    for model_result in run_results:
        model_id = model_result.get("model_id", "")
        if req.model_ids and model_id not in req.model_ids:
            continue
        for pr in model_result.get("prompt_results", []):
            tag = pr.get("tag", "")
            # Stable id: deterministic hash of run + model + prompt tag
            candidate_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"style-benchmark/{run_id}/{model_id}/{tag}",
            ))
            if candidate_id in existing_ids:
                continue

            score_pct = pr.get("score", 0.0) / 100.0
            signals = pr.get("signals", {})

            # Build the prompt message list matching the benchmark's actual request
            prompt_messages = [
                {"role": "system", "content": _STYLE_SYSTEM_PROMPT},
                {"role": "user",   "content": pr.get("user_prompt", tag)},
            ]

            new_candidates.append({
                "id":               candidate_id,
                "source":           "style-benchmark",
                "benchmark_run_id": run_id,
                "timestamp":        timestamp,
                "status":           "needs_review",
                "prompt_messages":  prompt_messages,
                "model_response":   pr.get("output", ""),
                "corrected_response": None,
                "quality_score":    round(score_pct, 4),
                "failure_reason":   _build_failure_reason(pr, signals),
                "failure_category": None,
                "task_id":          f"style/{tag}",
                "task_type":        "style-match",
                "task_name":        tag.replace("_", " ").title(),
                "model_id":         model_id,
                "model_name":       model_id,
                "node_id":          "",
                "gpu_id":           0,
                "tokens_per_sec":   0,
            })
            existing_ids.add(candidate_id)

    if new_candidates:
        sft_data_dir.mkdir(parents=True, exist_ok=True)
        with open(sft_file, "a", encoding="utf-8") as fh:
            for c in new_candidates:
                fh.write(json.dumps(c) + "\n")

    return {"imported": len(new_candidates), "skipped": 0}


# Excerpt of the system prompt used in benchmark_style.py — reproduced here
# so the SFT candidate captures the full generation context.
_STYLE_SYSTEM_PROMPT = (
    "You are a writing assistant. Your job is to write a Reddit reply that matches "
    "the voice, tone, and style of the provided samples exactly.\n\n"
    "Voice characteristics:\n"
    "- Casual engineer tone. Short punchy sentences.\n"
    "- No em dashes. No semicolons. No filler phrases.\n"
    "- Direct. Opinionated. Community-first."
)


def _build_failure_reason(pr: dict, signals: dict) -> str | None:
    """Return a human-readable failure reason string if there are violations."""
    reasons = []
    if signals.get("em_dash_count", 0) > 0:
        reasons.append(f"{signals['em_dash_count']} em dash(es)")
    if signals.get("semicolon_count", 0) > 0:
        reasons.append(f"{signals['semicolon_count']} semicolon(s)")
    if signals.get("filler_hits"):
        reasons.append(f"filler phrases: {', '.join(signals['filler_hits'])}")
    if not pr.get("output", "").strip():
        reasons.append("empty output")
    return "; ".join(reasons) if reasons else None


# ── POST /cancel ───────────────────────────────────────────────────────────────

@router.post("/cancel")
def cancel_style_benchmark() -> dict:
    """Kill the running writing style benchmark subprocess."""
    global _BENCH_RUNNING, _bench_proc

    if not _BENCH_RUNNING:
        raise HTTPException(404, "No writing style benchmark is currently running")

    if _bench_proc is not None:
        try:
            _bench_proc.terminate()
        except Exception as exc:
            logger.warning("Failed to terminate style benchmark: %s", exc)

    _BENCH_RUNNING = False
    _bench_proc = None
    return {"status": "cancelled"}
