"""Avocet -- train job queue API.

SQLite-backed job queue for finetune jobs. Replaces the ad-hoc
_running_procs dict in api.py with a persistent, inspectable queue.

Routes (all under /api/train when api.py mounts with prefix="/api/train"):
  GET  /jobs               -- list all jobs, newest first
  POST /jobs               -- create a new job
  GET  /jobs/{id}          -- get one job by id
  DELETE /jobs/{id}/cancel -- cancel a queued or running job
  GET  /jobs/{id}/run      -- SSE: run the job, stream stdout
  GET  /results            -- list completed models with training_info.json metrics

SQLite schema:
  CREATE TABLE IF NOT EXISTS jobs (
      id           TEXT PRIMARY KEY,
      type         TEXT NOT NULL,              -- 'classifier' | 'llm-sft'
      model_key    TEXT NOT NULL,
      status       TEXT NOT NULL DEFAULT 'queued',
      config_json  TEXT NOT NULL DEFAULT '{}',
      created_at   TEXT NOT NULL,
      started_at   TEXT,
      completed_at TEXT,
      error        TEXT
  )

Testability seam: _DB_PATH global, override via set_db_path().
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess as _subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_ROOT = Path(__file__).parent.parent.parent
_DB_PATH: Path = _ROOT / "data" / "train_jobs.db"
_MODELS_DIR: Path = _ROOT / "models"
_running_procs: dict[str, Any] = {}

router = APIRouter()


# -- Testability seams -------------------------------------------------

def set_db_path(path: Path) -> None:
    global _DB_PATH
    _DB_PATH = path

def set_models_dir(path: Path) -> None:
    global _MODELS_DIR
    _MODELS_DIR = path


# -- Database helpers --------------------------------------------------

@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_db() -> None:
    """Create jobs table if it does not exist. Called lazily per request."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                type         TEXT NOT NULL,
                model_key    TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'queued',
                config_json  TEXT NOT NULL DEFAULT '{}',
                created_at   TEXT NOT NULL,
                started_at   TEXT,
                completed_at TEXT,
                error        TEXT
            )
        """)


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


# -- GPU selection (copied from api.py) --------------------------------

def _best_cuda_device() -> str:
    """Return index of GPU with most free VRAM, or empty string."""
    try:
        out = _subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.free",
             "--format=csv,noheader,nounits"],
            text=True, timeout=5,
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


# -- Pydantic models ---------------------------------------------------

class CreateJobRequest(BaseModel):
    type: str           # "classifier" | "llm-sft"
    model_key: str      # e.g. "deberta-small"
    config_json: dict = {}


# -- Routes ------------------------------------------------------------

@router.get("/jobs")
def list_jobs() -> list[dict]:
    _init_db()
    with _db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/jobs")
def create_job(req: CreateJobRequest) -> dict:
    if req.type not in ("classifier", "llm-sft"):
        raise HTTPException(400, f"Unknown job type: {req.type!r}. Must be 'classifier' or 'llm-sft'.")
    _init_db()
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, type, model_key, status, config_json, created_at) "
            "VALUES (?, ?, ?, 'queued', ?, ?)",
            (job_id, req.type, req.model_key, json.dumps(req.config_json), now),
        )
    return {"id": job_id, "type": req.type, "model_key": req.model_key,
            "status": "queued", "config_json": req.config_json,
            "created_at": now, "started_at": None, "completed_at": None, "error": None}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    _init_db()
    with _db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Job {job_id!r} not found")
    return _row_to_dict(row)


@router.delete("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    _init_db()
    with _db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"Job {job_id!r} not found")
        if row["status"] not in ("queued", "running"):
            raise HTTPException(409, f"Job is {row['status']} -- cannot cancel")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE jobs SET status='cancelled', completed_at=? WHERE id=?", (now, job_id))
    proc = _running_procs.pop(job_id, None)
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except _subprocess.TimeoutExpired:
            proc.kill()
    return {"status": "cancelled"}


@router.get("/jobs/{job_id}/run")
def run_job(job_id: str) -> StreamingResponse:
    _init_db()
    with _db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Job {job_id!r} not found")
    if row["status"] != "queued":
        raise HTTPException(409, f"Job is {row['status']} -- only queued jobs can be run")
    job = _row_to_dict(row)

    def generate():
        python_bin = "/devl/miniconda3/envs/job-seeker-classifiers/bin/python"
        config = json.loads(job["config_json"] or "{}")
        model_key = job["model_key"]
        epochs = config.get("epochs", 5)

        if job["type"] == "classifier":
            script = str(_ROOT / "scripts" / "finetune_classifier.py")
            cmd = [python_bin, script, "--model", model_key, "--epochs", str(epochs)]
            data_dir = _ROOT / "data"
            for sf in config.get("score_files", []):
                resolved = (data_dir / sf).resolve()
                if str(resolved).startswith(str(data_dir.resolve())):
                    cmd.extend(["--score", str(resolved)])
        elif job["type"] == "llm-sft":
            script = str(_ROOT / "scripts" / "finetune_sft.py")
            cmd = [python_bin, script, "--model", model_key, "--epochs", str(epochs)]
        else:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Unknown job type: {job['type']}'})}\n\n"
            return

        proc_env = {**os.environ, "PYTORCH_ALLOC_CONF": "expandable_segments:True"}
        best_gpu = _best_cuda_device()
        if best_gpu:
            proc_env["CUDA_VISIBLE_DEVICES"] = best_gpu

        gpu_note = f"GPU {best_gpu}" if best_gpu else "CPU (no GPU found)"
        yield f"data: {json.dumps({'type': 'progress', 'message': f'[train] Using {gpu_note}'})}\n\n"

        now = datetime.now(timezone.utc).isoformat()
        with _db() as conn:
            conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (now, job_id))

        try:
            proc = _subprocess.Popen(
                cmd, stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                text=True, bufsize=1, cwd=str(_ROOT), env=proc_env,
            )
            _running_procs[job_id] = proc
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        yield f"data: {json.dumps({'type': 'progress', 'message': line})}\n\n"
                proc.wait()
                finished_at = datetime.now(timezone.utc).isoformat()
                if proc.returncode == 0:
                    with _db() as conn:
                        conn.execute(
                            "UPDATE jobs SET status='completed', completed_at=? WHERE id=?",
                            (finished_at, job_id))
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                else:
                    err = f"Process exited with code {proc.returncode}"
                    with _db() as conn:
                        conn.execute(
                            "UPDATE jobs SET status='failed', completed_at=?, error=? WHERE id=?",
                            (finished_at, err, job_id))
                    yield f"data: {json.dumps({'type': 'error', 'message': err})}\n\n"
            finally:
                _running_procs.pop(job_id, None)
        except Exception as exc:
            err = str(exc)
            with _db() as conn:
                conn.execute("UPDATE jobs SET status='failed', error=? WHERE id=?", (err, job_id))
            yield f"data: {json.dumps({'type': 'error', 'message': err})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/results")
def list_results() -> list[dict]:
    if not _MODELS_DIR.exists():
        return []
    results = []
    for sub in _MODELS_DIR.iterdir():
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
