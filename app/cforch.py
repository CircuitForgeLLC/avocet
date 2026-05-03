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
import tempfile
from pathlib import Path
from typing import Any

import urllib.parse

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
        "judge_url":       _coalesce(file_cfg.get("judge_url", ""),        "CF_JUDGE_URL"),
        "hf_token":        _coalesce(file_cfg.get("hf_token", ""),         "HF_TOKEN"),
    }


def _validate_service_url(url: str, param_name: str) -> str:
    """Validate that a URL is a well-formed http/https URL with a hostname.

    Guards against SSRF: only http/https is allowed; the URL must have a
    non-empty host. Does not enforce an allowlist — call sites are internal
    tooling, not a public API.
    """
    if not url:
        return url
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise HTTPException(400, f"{param_name}: not a valid URL")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, f"{param_name}: URL must start with http:// or https://")
    if not parsed.hostname:
        raise HTTPException(400, f"{param_name}: URL has no hostname")
    return url


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
            "id":     t.get("id", ""),
            "name":   t.get("name", ""),
            "type":   t.get("type", ""),
            "prompt": (t.get("prompt") or "").strip(),
            "system": (t.get("system") or "").strip(),
        })
        task_type = t.get("type", "")
        if task_type and task_type not in types_set:
            seen_types.append(task_type)
            types_set.add(task_type)

    return {"tasks": tasks, "types": seen_types}


# ── GET /models ────────────────────────────────────────────────────────────────

# Services and roles surfaced in the benchmark model picker.
# Covers all cf-orch service types that benchmark.py can route tasks to.
_BENCH_SERVICES = frozenset({
    "cf-text", "vllm",         # LLM text generation
    "cf-stt",                  # speech-to-text
    "cf-tts",                  # text-to-speech
    "cf-vision",               # image classification / embedding
    "cf-voice",                # audio context classification
})
_BENCH_ROLES = frozenset({
    "generator", "vlm",        # LLM roles
    "stt", "alm",              # speech recognition
    "tts",                     # speech synthesis
    "vision", "embedding",     # image understanding
    "classifier",              # audio classification (cf-voice)
})


@router.get("/models")
def get_models() -> dict:
    """Return model list from bench_models.yaml merged with locally installed models.

    bench_models.yaml entries are listed first and take precedence; any installed
    model whose repo_id is already present in the YAML is skipped.  Only models
    whose service is in _BENCH_SERVICES (cf-text, vllm, cf-stt, cf-tts, cf-vision,
    cf-voice) are surfaced from the installed registry.
    """
    cfg = _load_cforch_config()
    models_path = cfg.get("bench_models", "")

    models: list[dict] = []
    bench_ids: set[str] = set()

    if models_path:
        p = Path(models_path)
        if p.exists():
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                logger.warning("Failed to parse bench_models.yaml %s: %s", p, exc)
                raw = {}
            for m in (raw.get("models", []) or []):
                if not isinstance(m, dict):
                    continue
                model_id = m.get("id", "")
                models.append({
                    "name": m.get("name", ""),
                    "id": model_id,
                    "service": m.get("service", "ollama"),
                    "tags": m.get("tags", []) or [],
                    "vram_estimate_mb": m.get("vram_estimate_mb", 0),
                })
                if model_id:
                    bench_ids.add(model_id)

    # Merge installed generator models not already in bench_models.yaml.
    try:
        from app.models import list_installed  # local import avoids circular dependency at module load
        for installed in list_installed():
            model_id: str = installed.get("model_id") or ""
            service: str = installed.get("service") or ""
            role: str = installed.get("role") or ""
            if not model_id:
                continue
            if service not in _BENCH_SERVICES or role not in _BENCH_ROLES:
                continue
            if model_id in bench_ids:
                continue
            display_name = model_id.split("/", 1)[-1] if "/" in model_id else model_id
            models.append({
                "name": display_name,
                "id": model_id,
                "service": service,
                "tags": [role],
                "vram_estimate_mb": installed.get("vram_mb") or 0,
            })
            bench_ids.add(model_id)
    except Exception as exc:
        logger.warning("Could not merge installed models into model list: %s", exc)

    return {"models": models}


# ── GET /run ───────────────────────────────────────────────────────────────────

@router.get("/nodes")
def get_nodes() -> dict:
    """Proxy the coordinator's /api/nodes list, returning node_id + online status.

    Online is inferred from last_heartbeat: any node with a recent heartbeat is online.
    Returns an empty list if the coordinator is unreachable.
    """
    cfg = _load_cforch_config()
    coordinator_url = cfg.get("coordinator_url", "").rstrip("/")
    if not coordinator_url:
        return {"nodes": []}
    try:
        import httpx as _httpx
        resp = _httpx.get(f"{coordinator_url}/api/nodes", timeout=5.0)
        resp.raise_for_status()
        raw_nodes = resp.json().get("nodes", [])
        return {
            "nodes": [
                {
                    "node_id": n.get("node_id", ""),
                    "online": n.get("last_heartbeat") is not None,
                    "gpus": [
                        {
                            "gpu_id": g.get("gpu_id"),
                            "name": g.get("name", ""),
                            "vram_total_mb": g.get("vram_total_mb", 0),
                            "vram_free_mb": g.get("vram_free_mb", 0),
                        }
                        for g in n.get("gpus", [])
                    ],
                }
                for n in raw_nodes
            ]
        }
    except Exception as exc:
        logger.warning("Could not fetch nodes from coordinator: %s", exc)
        return {"nodes": []}


@router.get("/run")
def run_benchmark(
    task_ids: str = "",
    model_ids: str = "",
    model_tags: str = "",
    coordinator_url: str = "",
    ollama_url: str = "",
    judge_url: str = "",
    judge_backend: str = "chat",
    workers: int = 1,
    node_ids: str = "",
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
    cfg_judge_url   = cfg.get("judge_url", "")

    # Validate URL params before spawning the subprocess.
    # _validate_service_url raises HTTPException on bad input (caught by FastAPI before streaming starts).
    _validate_service_url(coordinator_url, "coordinator_url")
    _validate_service_url(ollama_url, "ollama_url")
    _validate_service_url(judge_url, "judge_url")

    def generate():
        global _BENCH_RUNNING, _bench_proc

        if not bench_script or not Path(bench_script).exists():
            yield f"data: {json.dumps({'type': 'error', 'message': 'bench_script not configured or not found'})}\n\n"
            return

        # Build effective models file: bench_models.yaml + any installed models
        # whose IDs were selected but are absent from the YAML (e.g. downloaded
        # via the Models view). Written to a temp file so benchmark.py sees one
        # unified list; cleaned up in the finally block.
        effective_models_file = bench_models
        _tmp_models_path: str | None = None

        if model_ids and bench_models and Path(bench_models).exists():
            requested_ids = set(model_ids.split(","))
            try:
                raw_bench = yaml.safe_load(Path(bench_models).read_text(encoding="utf-8")) or {}
                bench_entries: list[dict] = raw_bench.get("models", []) or []
                bench_id_set = {m.get("id", "") for m in bench_entries if isinstance(m, dict)}
                missing_ids = requested_ids - bench_id_set
                if missing_ids:
                    from app.models import list_installed
                    installed_map = {
                        m["model_id"]: m
                        for m in list_installed()
                        if m.get("model_id") and m.get("service") in _BENCH_SERVICES
                    }
                    extra: list[dict] = []
                    for mid in missing_ids:
                        if mid in installed_map:
                            inst = installed_map[mid]
                            entry: dict[str, Any] = {
                                "id": mid,
                                "name": mid.split("/", 1)[-1] if "/" in mid else mid,
                                "service": inst.get("service", "cf-text"),
                                "vram_estimate_mb": inst.get("vram_mb") or 0,
                                "tags": [inst.get("role", "generator")],
                                "temperature": 0.0,
                            }
                            local_path = inst.get("path", "") or inst.get("local_path", "")
                            if local_path:
                                entry["model_path"] = local_path
                            extra.append(entry)
                    if extra:
                        merged = {"models": bench_entries + extra}
                        tf = tempfile.NamedTemporaryFile(
                            mode="w", suffix=".yaml", delete=False,
                            prefix="avocet_bench_models_",
                        )
                        yaml.dump(merged, tf)
                        tf.close()
                        _tmp_models_path = tf.name
                        effective_models_file = _tmp_models_path
            except Exception as exc:
                logger.warning("Could not merge installed models into temp bench file: %s", exc)

        cmd = [
            python_bin,
            bench_script,
            "--tasks", bench_tasks,
            "--models", effective_models_file,
            "--output", results_dir,
        ]

        if task_ids:
            cmd.extend(["--filter-tasks"] + task_ids.split(","))
        if model_ids:
            cmd.extend(["--filter-models"] + model_ids.split(","))
        if model_tags:
            cmd.extend(["--filter-tags"] + model_tags.split(","))

        # query param overrides config, config overrides env var (already resolved by _load_cforch_config)
        effective_coordinator = coordinator_url if coordinator_url else cfg_coordinator
        effective_ollama      = ollama_url      if ollama_url      else cfg_ollama
        if effective_coordinator:
            cmd.extend(["--coordinator", effective_coordinator])
        if effective_ollama:
            cmd.extend(["--ollama-url", effective_ollama])
        effective_judge = judge_url if judge_url else cfg_judge_url
        if effective_judge:
            cmd.extend(["--judge-url", effective_judge])
        if judge_backend and judge_backend != "chat":
            cmd.extend(["--judge-backend", judge_backend])
        if workers > 1:
            cmd.extend(["--workers", str(workers)])
        if node_ids:
            cmd.extend(["--nodes"] + node_ids.split(","))

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
            if _tmp_models_path:
                try:
                    os.unlink(_tmp_models_path)
                except OSError:
                    pass

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
        "judge_url":       cfg.get("judge_url", ""),
        "license_key_set": bool(cfg.get("license_key", "")),
        "source": "env" if not _config_file().exists() else "yaml+env",
    }


# ── GET /results ───────────────────────────────────────────────────────────────

@router.get("/results")
def get_results() -> list:
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
