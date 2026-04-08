"""Avocet — SFT candidate import and correction API.

All endpoints are registered on `router` (a FastAPI APIRouter).
api.py includes this router with prefix="/api/sft".

Module-level globals (_SFT_DATA_DIR, _SFT_CONFIG_DIR) follow the same
testability pattern as api.py — override them via set_sft_data_dir() and
set_sft_config_dir() in test fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    d = raw.get("sft", {}).get("bench_results_dir", "")
    return Path(d) if d else Path("/nonexistent-bench-results")


def _candidates_file() -> Path:
    return _SFT_DATA_DIR / "sft_candidates.jsonl"


def _approved_file() -> Path:
    return _SFT_DATA_DIR / "sft_approved.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(r) for r in records)
    path.write_text(content + ("\n" if records else ""), encoding="utf-8")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _read_candidates() -> list[dict]:
    return _read_jsonl(_candidates_file())


def _write_candidates(records: list[dict]) -> None:
    _write_jsonl(_candidates_file(), records)


# ── GET /runs ──────────────────────────────────────────────────────────────

@router.get("/runs")
def get_runs():
    """List available benchmark runs in the configured bench_results_dir."""
    from scripts.sft_import import discover_runs
    bench_dir = _get_bench_results_dir()
    existing = _read_candidates()
    imported_run_ids = {r.get("benchmark_run_id") for r in existing}
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
