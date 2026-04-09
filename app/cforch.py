"""Avocet — cf-orch benchmark integration API.

Wraps cf-orch's benchmark.py script and exposes it via the Avocet API.
Config is read from label_tool.yaml under the `cforch:` key.

All endpoints are registered on `router` (a FastAPI APIRouter).
api.py includes this router with prefix="/api/cforch".

Module-level globals (_CONFIG_DIR, _BENCH_RUNNING, _bench_proc) follow the
same testability pattern as sft.py — override _CONFIG_DIR via set_config_dir()
in test fixtures.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess as _subprocess
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_CONFIG_DIR: Path | None = None   # override in tests
_BENCH_RUNNING: bool = False
_bench_proc: Any = None            # live Popen object while benchmark runs

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


def _load_cforch_config() -> dict:
    """Read label_tool.yaml cforch section, falling back to environment variables.

    Priority (highest to lowest):
      1. label_tool.yaml cforch: key
      2. Environment variables (CF_ORCH_URL, CF_LICENSE_KEY, OLLAMA_HOST, OLLAMA_MODEL)
    """
    f = _config_file()
    file_cfg: dict = {}
    if f.exists():
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            file_cfg = raw.get("cforch", {}) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse cforch config %s: %s", f, exc)

    # Env var fallbacks — only used when the yaml key is absent or empty
    def _coalesce(file_val: str, env_key: str) -> str:
        return file_val if file_val else os.environ.get(env_key, "")

    return {
        **file_cfg,
        "coordinator_url": _coalesce(file_cfg.get("coordinator_url", ""), "CF_ORCH_URL"),
        "license_key":     _coalesce(file_cfg.get("license_key", ""),     "CF_LICENSE_KEY"),
        "ollama_url":      _coalesce(file_cfg.get("ollama_url", ""),       "OLLAMA_HOST"),
        "ollama_model":    _coalesce(file_cfg.get("ollama_model", ""),     "OLLAMA_MODEL"),
    }


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from a string."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def _find_latest_summary(results_dir: str | None) -> Path | None:
    """Find the newest summary.json under results_dir, or None if not found."""
    if not results_dir:
        return None
    rdir = Path(results_dir)
    if not rdir.exists():
        return None
    # Subdirs are named YYYY-MM-DD-HHMMSS; sort lexicographically for chronological order
    subdirs = sorted(
        [d for d in rdir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    for subdir in reversed(subdirs):
        summary = subdir / "summary.json"
        if summary.exists():
            return summary
    return None


# ── GET /tasks ─────────────────────────────────────────────────────────────────

@router.get("/tasks")
def get_tasks() -> dict:
    """Return task list from bench_tasks.yaml."""
    cfg = _load_cforch_config()
    tasks_path = cfg.get("bench_tasks", "")
    if not tasks_path:
        return {"tasks": [], "types": []}

    p = Path(tasks_path)
    if not p.exists():
        return {"tasks": [], "types": []}

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse bench_tasks.yaml %s: %s", p, exc)
        return {"tasks": [], "types": []}

    tasks_raw = raw.get("tasks", []) or []
    tasks: list[dict] = []
    seen_types: list[str] = []
    types_set: set[str] = set()

    for t in tasks_raw:
        if not isinstance(t, dict):
            continue
        tasks.append({
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "type": t.get("type", ""),
        })
        task_type = t.get("type", "")
        if task_type and task_type not in types_set:
            seen_types.append(task_type)
            types_set.add(task_type)

    return {"tasks": tasks, "types": seen_types}


# ── GET /models ────────────────────────────────────────────────────────────────

@router.get("/models")
def get_models() -> dict:
    """Return model list from bench_models.yaml."""
    cfg = _load_cforch_config()
    models_path = cfg.get("bench_models", "")
    if not models_path:
        return {"models": []}

    p = Path(models_path)
    if not p.exists():
        return {"models": []}

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse bench_models.yaml %s: %s", p, exc)
        return {"models": []}

    models_raw = raw.get("models", []) or []
    models: list[dict] = []
    for m in models_raw:
        if not isinstance(m, dict):
            continue
        models.append({
            "name": m.get("name", ""),
            "id": m.get("id", ""),
            "service": m.get("service", "ollama"),
            "tags": m.get("tags", []) or [],
            "vram_estimate_mb": m.get("vram_estimate_mb", 0),
        })

    return {"models": models}


# ── GET /run ───────────────────────────────────────────────────────────────────

@router.get("/run")
def run_benchmark(
    task_ids: str = "",
    model_tags: str = "",
    coordinator_url: str = "",
    ollama_url: str = "",
) -> StreamingResponse:
    """Spawn cf-orch benchmark.py and stream stdout as SSE progress events."""
    global _BENCH_RUNNING, _bench_proc

    if _BENCH_RUNNING:
        raise HTTPException(409, "A benchmark is already running")

    cfg = _load_cforch_config()
    bench_script = cfg.get("bench_script", "")
    bench_tasks = cfg.get("bench_tasks", "")
    bench_models = cfg.get("bench_models", "")
    results_dir = cfg.get("results_dir", "")
    python_bin = cfg.get("python_bin", "/devl/miniconda3/envs/cf/bin/python")
    cfg_coordinator = cfg.get("coordinator_url", "")
    cfg_ollama      = cfg.get("ollama_url", "")
    cfg_license_key = cfg.get("license_key", "")

    def generate():
        global _BENCH_RUNNING, _bench_proc

        if not bench_script or not Path(bench_script).exists():
            yield f"data: {json.dumps({'type': 'error', 'message': 'bench_script not configured or not found'})}\n\n"
            return

        cmd = [
            python_bin,
            bench_script,
            "--tasks", bench_tasks,
            "--models", bench_models,
            "--output", results_dir,
        ]

        if task_ids:
            cmd.extend(["--filter-tasks"] + task_ids.split(","))
        if model_tags:
            cmd.extend(["--filter-tags"] + model_tags.split(","))

        # query param overrides config, config overrides env var (already resolved by _load_cforch_config)
        effective_coordinator = coordinator_url if coordinator_url else cfg_coordinator
        effective_ollama      = ollama_url      if ollama_url      else cfg_ollama
        if effective_coordinator:
            cmd.extend(["--coordinator", effective_coordinator])
        if effective_ollama:
            cmd.extend(["--ollama-url", effective_ollama])

        # Pass license key as env var so subprocess can authenticate with cf-orch
        proc_env = {**os.environ}
        if cfg_license_key:
            proc_env["CF_LICENSE_KEY"] = cfg_license_key

        _BENCH_RUNNING = True
        try:
            proc = _subprocess.Popen(
                cmd,
                stdout=_subprocess.PIPE,
                stderr=_subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=proc_env,
            )
            _bench_proc = proc
            try:
                for line in proc.stdout:
                    line = _strip_ansi(line.rstrip())
                    if line:
                        yield f"data: {json.dumps({'type': 'progress', 'message': line})}\n\n"
                proc.wait()
                if proc.returncode == 0:
                    summary_path = _find_latest_summary(results_dir)
                    if summary_path is not None:
                        try:
                            summary = json.loads(summary_path.read_text(encoding="utf-8"))
                            yield f"data: {json.dumps({'type': 'result', 'summary': summary})}\n\n"
                        except Exception as exc:
                            logger.warning("Failed to read summary.json: %s", exc)
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


# ── GET /config ────────────────────────────────────────────────────────────────

@router.get("/config")
def get_cforch_config() -> dict:
    """Return resolved cf-orch connection config (env vars merged with yaml).

    Redacts license_key — only returns whether it is set, not the value.
    Used by the Settings UI to show current connection state.
    """
    cfg = _load_cforch_config()
    return {
        "coordinator_url": cfg.get("coordinator_url", ""),
        "ollama_url":      cfg.get("ollama_url", ""),
        "ollama_model":    cfg.get("ollama_model", ""),
        "license_key_set": bool(cfg.get("license_key", "")),
        "source": "env" if not _config_file().exists() else "yaml+env",
    }


# ── GET /results ───────────────────────────────────────────────────────────────

@router.get("/results")
def get_results() -> dict:
    """Return the latest benchmark summary.json from results_dir."""
    cfg = _load_cforch_config()
    results_dir = cfg.get("results_dir", "")
    summary_path = _find_latest_summary(results_dir)
    if summary_path is None:
        raise HTTPException(404, "No benchmark results found")
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Failed to read summary.json: {exc}") from exc


# ── POST /cancel ───────────────────────────────────────────────────────────────

@router.post("/cancel")
def cancel_benchmark() -> dict:
    """Kill the running benchmark subprocess."""
    global _BENCH_RUNNING, _bench_proc

    if not _BENCH_RUNNING:
        raise HTTPException(404, "No benchmark is currently running")

    if _bench_proc is not None:
        try:
            _bench_proc.terminate()
        except Exception as exc:
            logger.warning("Failed to terminate benchmark process: %s", exc)

    _BENCH_RUNNING = False
    _bench_proc = None
    return {"status": "cancelled"}
