"""Avocet -- dashboard aggregate API.

GET /api/dashboard returns the current flywheel state:
  labeled_since_last_eval  -- items labeled after the most recent eval run
  last_eval_timestamp      -- ISO timestamp of newest bench_results summary
  last_eval_best_score     -- best macro_f1 from that summary
  active_jobs              -- jobs with status queued or running
  corrections_pending      -- sft_candidates with status=needs_review
  corrections_export_ready -- approved sft candidates with non-blank correction
  signals                  -- computed booleans for UI nudge indicators

Thresholds in label_tool.yaml pipeline: section:
  pipeline:
    data_eval_threshold: 50    # labeled items since last eval to trigger nudge
    eval_train_threshold: 0.05 # improvement delta needed before retraining (future)
"""
from __future__ import annotations

import json
import logging
import yaml
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_DATA_DIR: Path = _ROOT / "data"
_CONFIG_DIR: Path | None = None

router = APIRouter()

_DEFAULT_DATA_EVAL_THRESHOLD = 50
_DEFAULT_EVAL_TRAIN_THRESHOLD = 0.05


def set_data_dir(path: Path) -> None:
    global _DATA_DIR
    _DATA_DIR = path

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path

def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"

def _load_thresholds() -> tuple[int, float]:
    f = _config_file()
    if f.exists():
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            pipeline = raw.get("pipeline", {}) or {}
            return (
                int(pipeline.get("data_eval_threshold", _DEFAULT_DATA_EVAL_THRESHOLD)),
                float(pipeline.get("eval_train_threshold", _DEFAULT_EVAL_TRAIN_THRESHOLD)),
            )
        except Exception as exc:
            logger.warning("Failed to read pipeline thresholds: %s", exc)
    return _DEFAULT_DATA_EVAL_THRESHOLD, _DEFAULT_EVAL_TRAIN_THRESHOLD

def _load_score_records() -> list[dict]:
    path = _DATA_DIR / "email_score.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records

def _find_latest_eval(results_dir_override: str = "") -> tuple[str | None, float | None]:
    """Return (iso_timestamp, best_macro_f1) from the newest bench_results summary.

    Checks results_dir from cforch config if set, then falls back to
    _ROOT/bench_results/. Returns (None, None) if no results exist.
    """
    candidates = []
    if results_dir_override:
        candidates.append(Path(results_dir_override))
    else:
        f = _config_file()
        if f.exists():
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                rd = (raw.get("cforch", {}) or {}).get("results_dir", "")
                if rd:
                    candidates.append(Path(rd))
            except Exception as exc:
                logger.warning("Failed to read cforch.results_dir from config: %s", exc)
    candidates.append(_ROOT / "bench_results")

    for rdir in candidates:
        if not rdir.exists():
            continue
        subdirs = sorted([d for d in rdir.iterdir() if d.is_dir()], key=lambda d: d.name)
        for subdir in reversed(subdirs):
            summary = subdir / "summary.json"
            if summary.exists():
                try:
                    data = json.loads(summary.read_text(encoding="utf-8"))
                    ts = data.get("timestamp") or subdir.name
                    score = data.get("best_macro_f1") or data.get("macro_f1")
                    return ts, (float(score) if isinstance(score, (int, float)) else None)
                except Exception as exc:
                    logger.warning("Failed to parse summary.json at %s: %s", summary, exc)
    return None, None

def _count_corrections() -> tuple[int, int]:
    """Return (pending_count, export_ready_count)."""
    pending = 0
    export_ready = 0
    candidates_path = _DATA_DIR / "sft_candidates.jsonl"
    approved_path   = _DATA_DIR / "sft_approved.jsonl"
    if candidates_path.exists():
        for line in candidates_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("status") == "needs_review":
                    pending += 1
            except json.JSONDecodeError:
                pass
    if approved_path.exists():
        for line in approved_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if (r.get("status") == "approved"
                        and r.get("corrected_response")
                        and str(r["corrected_response"]).strip()):
                    export_ready += 1
            except json.JSONDecodeError:
                pass
    return pending, export_ready

def _get_active_jobs() -> list[dict]:
    """Query train SQLite DB for queued/running jobs. Returns [] if DB absent."""
    try:
        from app.train.train import _DB_PATH, _db, _init_db
        if not _DB_PATH.exists():
            return []
        _init_db()
        with _db() as conn:
            rows = conn.execute(
                "SELECT id, type, model_key, status FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
        return [{"id": r["id"], "type": r["type"], "model_key": r["model_key"], "status": r["status"]} for r in rows]
    except Exception as exc:
        logger.warning("Failed to query train jobs DB: %s", exc)
        return []

def _count_labeled_since(since_ts: str | None) -> int:
    records = _load_score_records()
    if since_ts is None:
        return len(records)
    return sum(1 for r in records if r.get("labeled_at", "") > since_ts)


@router.get("/dashboard")
def get_dashboard() -> dict:
    data_eval_threshold, eval_train_threshold = _load_thresholds()
    last_eval_ts, last_eval_score = _find_latest_eval()
    labeled_since = _count_labeled_since(last_eval_ts)
    corrections_pending, corrections_export_ready = _count_corrections()
    active_jobs = _get_active_jobs()
    return {
        "labeled_since_last_eval": labeled_since,
        "last_eval_timestamp": last_eval_ts,
        "last_eval_best_score": last_eval_score,
        "active_jobs": active_jobs,
        "corrections_pending": corrections_pending,
        "corrections_export_ready": corrections_export_ready,
        "signals": {
            "data_to_eval":   labeled_since >= data_eval_threshold,
            "eval_to_train":  False,   # future: implement delta-F1 comparison
            "train_to_fleet": False,   # future: implement fleet sync signal
        },
    }
