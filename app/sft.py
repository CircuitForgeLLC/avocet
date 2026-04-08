"""Avocet — SFT candidate import and correction API.

All endpoints are registered on `router` (a FastAPI APIRouter).
api.py includes this router with prefix="/api/sft".

Module-level globals (_SFT_DATA_DIR, _SFT_CONFIG_DIR) follow the same
testability pattern as api.py — override them via set_sft_data_dir() and
set_sft_config_dir() in test fixtures.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.utils import append_jsonl, read_jsonl, write_jsonl

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_SFT_DATA_DIR: Path = _ROOT / "data"
_SFT_CONFIG_DIR: Path | None = None

router = APIRouter()


# ── Testability seams ──────────────────────────────────────────────────────

def set_sft_data_dir(path: Path) -> None:
    global _SFT_DATA_DIR
    _SFT_DATA_DIR = path


def set_sft_config_dir(path: Path | None) -> None:
    global _SFT_CONFIG_DIR
    _SFT_CONFIG_DIR = path


# ── Internal helpers ───────────────────────────────────────────────────────

def _config_file() -> Path:
    if _SFT_CONFIG_DIR is not None:
        return _SFT_CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def _get_bench_results_dir() -> Path:
    f = _config_file()
    if not f.exists():
        return Path("/nonexistent-bench-results")
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse SFT config %s: %s", f, exc)
        return Path("/nonexistent-bench-results")
    d = raw.get("sft", {}).get("bench_results_dir", "")
    return Path(d) if d else Path("/nonexistent-bench-results")


def _candidates_file() -> Path:
    return _SFT_DATA_DIR / "sft_candidates.jsonl"


def _approved_file() -> Path:
    return _SFT_DATA_DIR / "sft_approved.jsonl"


def _read_candidates() -> list[dict]:
    return read_jsonl(_candidates_file())


def _write_candidates(records: list[dict]) -> None:
    write_jsonl(_candidates_file(), records)


# ── GET /runs ──────────────────────────────────────────────────────────────

@router.get("/runs")
def get_runs():
    """List available benchmark runs in the configured bench_results_dir."""
    from scripts.sft_import import discover_runs
    bench_dir = _get_bench_results_dir()
    existing = _read_candidates()
    # benchmark_run_id in each record equals the run's directory name by cf-orch convention
    imported_run_ids = {
        r["benchmark_run_id"]
        for r in existing
        if r.get("benchmark_run_id") is not None
    }
    runs = discover_runs(bench_dir)
    return [
        {
            "run_id": r["run_id"],
            "timestamp": r["timestamp"],
            "candidate_count": r["candidate_count"],
            "already_imported": r["run_id"] in imported_run_ids,
        }
        for r in runs
    ]


# ── POST /import ───────────────────────────────────────────────────────────

class ImportRequest(BaseModel):
    run_id: str


@router.post("/import")
def post_import(req: ImportRequest):
    """Import one benchmark run's sft_candidates.jsonl into the local data dir."""
    from scripts.sft_import import discover_runs, import_run
    bench_dir = _get_bench_results_dir()
    runs = discover_runs(bench_dir)
    run = next((r for r in runs if r["run_id"] == req.run_id), None)
    if run is None:
        raise HTTPException(404, f"Run {req.run_id!r} not found in bench_results_dir")
    return import_run(run["sft_path"], _SFT_DATA_DIR)


# ── GET /queue ─────────────────────────────────────────────────────────────

@router.get("/queue")
def get_queue(page: int = 1, per_page: int = 20):
    """Return paginated needs_review candidates."""
    records = _read_candidates()
    pending = [r for r in records if r.get("status") == "needs_review"]
    start = (page - 1) * per_page
    return {
        "items": pending[start:start + per_page],
        "total": len(pending),
        "page": page,
        "per_page": per_page,
    }


# ── POST /submit ───────────────────────────────────────────────────────────

class SubmitRequest(BaseModel):
    id: str
    action: str  # "correct" | "discard" | "flag"
    corrected_response: str | None = None


@router.post("/submit")
def post_submit(req: SubmitRequest):
    """Record a reviewer decision for one SFT candidate."""
    if req.action not in ("correct", "discard", "flag"):
        raise HTTPException(422, f"Unknown action {req.action!r}")
    if req.action == "correct":
        if not req.corrected_response or not req.corrected_response.strip():
            raise HTTPException(422, "corrected_response must be non-empty when action is 'correct'")

    records = _read_candidates()
    idx = next((i for i, r in enumerate(records) if r.get("id") == req.id), None)
    if idx is None:
        raise HTTPException(404, f"Record {req.id!r} not found")

    record = records[idx]
    if record.get("status") != "needs_review":
        raise HTTPException(409, f"Record is not in needs_review state (current: {record.get('status')})")

    if req.action == "correct":
        records[idx] = {**record, "status": "approved", "corrected_response": req.corrected_response}
        _write_candidates(records)
        append_jsonl(_approved_file(), records[idx])
    elif req.action == "discard":
        records[idx] = {**record, "status": "discarded"}
        _write_candidates(records)
    else:  # flag
        records[idx] = {**record, "status": "model_rejected"}
        _write_candidates(records)

    return {"ok": True}


# ── POST /undo ─────────────────────────────────────────────────────────────

class UndoRequest(BaseModel):
    id: str


@router.post("/undo")
def post_undo(req: UndoRequest):
    """Restore a previously actioned candidate back to needs_review."""
    records = _read_candidates()
    idx = next((i for i, r in enumerate(records) if r.get("id") == req.id), None)
    if idx is None:
        raise HTTPException(404, f"Record {req.id!r} not found")

    record = records[idx]
    old_status = record.get("status")
    if old_status == "needs_review":
        raise HTTPException(409, "Record is already in needs_review state")

    records[idx] = {**record, "status": "needs_review", "corrected_response": None}
    _write_candidates(records)

    # If it was approved, remove from the approved file too
    if old_status == "approved":
        approved = read_jsonl(_approved_file())
        write_jsonl(_approved_file(), [r for r in approved if r.get("id") != req.id])

    return {"ok": True}
