"""Avocet — VaporTrade cost-benchmark/load-test GUI integration.

Structural sibling to app/plans_bench.py -- same subprocess+SSE-streaming
shape, same results-list/latest/by-id contract, same testability seam
(_RESULTS_DIR overridable). The real difference: this router shells out
to ANOTHER product's repo (VaporTrade's bench/ scripts) rather than a
script inside Avocet itself, and reads results from VaporTrade's own
bench/results/ directory rather than duplicating them into Avocet's own
data/ dir (spec Component 5: "one source of truth for did this run
happen and what did it produce").

api.py includes this router with prefix="/api/vaportrade-bench".
"""
from __future__ import annotations

import json
import logging
import re
import subprocess as _subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_CONFIG_DIR: Path | None = None
_BENCH_RUNNING: bool = False
_bench_proc: Any = None

router = APIRouter()


def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path


def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def _load_config() -> dict:
    f = _config_file()
    cfg: dict = {}
    if f.exists():
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            cfg = raw.get("vaportrade_bench", {}) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse vaportrade_bench config %s: %s", f, exc)
    return {
        "repo_path":  cfg.get("repo_path", ""),
        "python_bin": cfg.get("python_bin", "python3"),
        "ssh_host":   cfg.get("ssh_host", ""),
    }


# _RESULTS_DIR is a MODULE-LEVEL var read fresh inside each request handler
# below (not cached at import time) so tests can monkeypatch it per-test --
# it's recomputed from _load_config() unless a test has overridden it
# directly (see test_vaportrade_bench.py's monkeypatch.setattr pattern).
_RESULTS_DIR: Path | None = None


def _results_dir() -> Path:
    if _RESULTS_DIR is not None:
        return _RESULTS_DIR
    repo_path = _load_config()["repo_path"]
    return Path(repo_path) / "bench" / "results"


@router.get("/results")
def list_results() -> list[dict]:
    d = _results_dir()
    if not d.exists():
        return []
    runs = []
    for f in sorted(d.glob("report-*.md"), reverse=True):
        runs.append({"run_id": f.stem, "filename": f.name})
    return runs


@router.get("/results/latest")
def get_latest_results() -> dict:
    d = _results_dir()
    files = sorted(d.glob("report-*.md")) if d.exists() else []
    if not files:
        raise HTTPException(404, "No benchmark results found")
    return {"filename": files[-1].name, "content": files[-1].read_text(encoding="utf-8")}


@router.get("/results/{run_id}")
def get_results_by_run_id(run_id: str) -> dict:
    if not re.fullmatch(r"report-\d{8}-\d{6}", run_id):
        raise HTTPException(400, "Invalid run_id — expected report-YYYYMMDD-HHMMSS")
    d = _results_dir()
    f = (d / f"{run_id}.md").resolve()
    # Defense-in-depth on top of the regex above: verify the resolved path
    # is still contained within the results dir before touching the
    # filesystem (catches any traversal shape the regex might miss).
    if not str(f).startswith(str(d.resolve()) + "/"):
        raise HTTPException(400, "Invalid run_id")
    if not f.exists():
        raise HTTPException(404, f"Results not found: {run_id}")
    return {"filename": f.name, "content": f.read_text(encoding="utf-8")}


def _build_command(kind: str, users: int, label: str, cfg: dict) -> list[str]:
    repo_path, python_bin = cfg["repo_path"], cfg["python_bin"]
    if kind == "cost":
        script_cmd = ["env", "VT_BENCH=1", python_bin, "bench/cost_bench.py"]
    elif kind == "load":
        # Port 8951 matches bench/scratch_server.py's DEFAULT_PORT
        # (VaporTrade repo, Task 4) -- the operator must have that scratch
        # server already running (per bench/README.md) before triggering
        # a load run here; this router doesn't launch it. Both the manual
        # README flow and this Avocet-triggered flow target the SAME
        # fixed port for exactly this reason (pre-flight ruling,
        # 2026-08-27 -- see this plan's ledger).
        script_cmd = [python_bin, "-m", "locust", "-f", "bench/locustfile.py",
                       "--headless", "--host", "http://127.0.0.1:8951",
                       "--users", str(users), "--spawn-rate", "5", "--run-time", "2m",
                       "--csv", f"bench/results/load-{label}"]
    else:
        raise ValueError(f"unknown kind: {kind}")

    if cfg["ssh_host"]:
        remote = f"cd '{repo_path}' && " + " ".join(script_cmd)
        return ["ssh", "-T", cfg["ssh_host"], remote]
    return script_cmd  # local Popen uses cwd=repo_path (set by the caller)


@router.get("/run")
def run_vaportrade_bench(
    kind: str = Query(..., description="'cost' or 'load'"),
    users: int = Query(10, ge=1, le=1000, description="Locust virtual users (kind=load only)"),
    label: Literal["single", "fleet"] = Query("single", description="'single' or 'fleet' (kind=load only, spec Component 3)"),
) -> StreamingResponse:
    global _BENCH_RUNNING, _bench_proc

    if kind not in ("cost", "load"):
        raise HTTPException(400, "kind must be 'cost' or 'load'")
    if _BENCH_RUNNING:
        raise HTTPException(409, "A VaporTrade benchmark is already running")

    cfg = _load_config()
    if not cfg["repo_path"]:
        raise HTTPException(500, "vaportrade_bench.repo_path not configured in label_tool.yaml")
    cmd = _build_command(kind, users, label, cfg)

    def generate():
        global _BENCH_RUNNING, _bench_proc
        _BENCH_RUNNING = True
        try:
            proc = _subprocess.Popen(
                cmd, stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                text=True, bufsize=1,
                cwd=cfg["repo_path"] if not cfg["ssh_host"] else None,
            )
            _bench_proc = proc
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        yield f"data: {json.dumps({'type': 'progress', 'message': line})}\n\n"
                proc.wait()
                if proc.returncode == 0:
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Process exited with code {proc.returncode}'})}\n\n"
            finally:
                _bench_proc = None
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        finally:
            _BENCH_RUNNING = False

    return StreamingResponse(generate(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/cancel")
def cancel_vaportrade_bench() -> dict:
    global _BENCH_RUNNING, _bench_proc
    if _bench_proc is not None:
        _bench_proc.terminate()
        _BENCH_RUNNING = False
        return {"ok": True, "message": "Cancelled"}
    return {"ok": False, "message": "No benchmark running"}
