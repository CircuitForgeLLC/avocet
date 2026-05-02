"""Avocet -- label queue API.

All label/skip/discard/undo/stats/config endpoints.
Extracted from app/api.py as part of the v2 domain split.
"""
from __future__ import annotations

import hashlib
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.utils import append_jsonl, read_jsonl, write_jsonl

_ROOT = Path(__file__).parent.parent.parent
_DATA_DIR: Path = _ROOT / "data"
_CONFIG_DIR: Path | None = None
_last_action: dict | None = None

router = APIRouter()


def set_data_dir(path: Path) -> None:
    global _DATA_DIR
    _DATA_DIR = path

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path

def reset_last_action() -> None:
    global _last_action
    _last_action = None

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

def _item_id(item: dict) -> str:
    key = (item.get("subject", "") + (item.get("body", "") or "")[:100])
    return hashlib.md5(key.encode("utf-8", errors="replace")).hexdigest()

def _normalize(item: dict) -> dict:
    return {
        "id":      item.get("id") or _item_id(item),
        "subject": item.get("subject", ""),
        "body":    item.get("body", ""),
        "from":    item.get("from") or item.get("from_addr", ""),
        "date":    item.get("date", ""),
        "source":  item.get("source") or item.get("account", ""),
    }

_LABEL_META = [
    {"name": "interview_scheduled", "emoji": "\U0001f4c5", "color": "#4CAF50", "key": "1"},
    {"name": "offer_received",      "emoji": "\U0001f389", "color": "#2196F3", "key": "2"},
    {"name": "rejected",            "emoji": "❌",     "color": "#F44336", "key": "3"},
    {"name": "positive_response",   "emoji": "\U0001f44d", "color": "#FF9800", "key": "4"},
    {"name": "survey_received",     "emoji": "\U0001f4cb", "color": "#9C27B0", "key": "5"},
    {"name": "neutral",             "emoji": "⬜",     "color": "#607D8B", "key": "6"},
    {"name": "event_rescheduled",   "emoji": "\U0001f504", "color": "#FF5722", "key": "7"},
    {"name": "digest",              "emoji": "\U0001f4f0", "color": "#00BCD4", "key": "8"},
    {"name": "new_lead",            "emoji": "\U0001f91d", "color": "#009688", "key": "9"},
    {"name": "hired",               "emoji": "\U0001f38a", "color": "#FFC107", "key": "h"},
]

@router.get("/queue")
def get_queue(limit: int = Query(default=10, ge=1, le=50)):
    items = read_jsonl(_queue_file())
    return {"items": [_normalize(x) for x in items[:limit]], "total": len(items)}

class LabelRequest(BaseModel):
    id: str
    label: str

@router.post("/label")
def post_label(req: LabelRequest):
    global _last_action
    items = read_jsonl(_queue_file())
    match = next((x for x in items if _normalize(x)["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    record = {**match, "label": req.label,
              "labeled_at": datetime.now(timezone.utc).isoformat()}
    append_jsonl(_score_file(), record)
    write_jsonl(_queue_file(), [x for x in items if _normalize(x)["id"] != req.id])
    _last_action = {"type": "label", "item": match, "label": req.label}
    return {"ok": True}

class SkipRequest(BaseModel):
    id: str

@router.post("/skip")
def post_skip(req: SkipRequest):
    global _last_action
    items = read_jsonl(_queue_file())
    match = next((x for x in items if _normalize(x)["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    reordered = [x for x in items if _normalize(x)["id"] != req.id] + [match]
    write_jsonl(_queue_file(), reordered)
    _last_action = {"type": "skip", "item": match}
    return {"ok": True}

class DiscardRequest(BaseModel):
    id: str

@router.post("/discard")
def post_discard(req: DiscardRequest):
    global _last_action
    items = read_jsonl(_queue_file())
    match = next((x for x in items if _normalize(x)["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    record = {**match, "label": "__discarded__",
              "discarded_at": datetime.now(timezone.utc).isoformat()}
    append_jsonl(_discarded_file(), record)
    write_jsonl(_queue_file(), [x for x in items if _normalize(x)["id"] != req.id])
    _last_action = {"type": "discard", "item": match}
    return {"ok": True}

@router.delete("/label/undo")
def delete_undo():
    global _last_action
    if not _last_action:
        raise HTTPException(404, "No action to undo")
    action = _last_action
    item = action["item"]
    if action["type"] == "label":
        records = read_jsonl(_score_file())
        if not records:
            raise HTTPException(409, "Score file is empty -- cannot undo label")
        write_jsonl(_score_file(), records[:-1])
        items = read_jsonl(_queue_file())
        write_jsonl(_queue_file(), [item] + items)
    elif action["type"] == "discard":
        records = read_jsonl(_discarded_file())
        if not records:
            raise HTTPException(409, "Discarded file is empty -- cannot undo discard")
        write_jsonl(_discarded_file(), records[:-1])
        items = read_jsonl(_queue_file())
        write_jsonl(_queue_file(), [item] + items)
    elif action["type"] == "skip":
        items = read_jsonl(_queue_file())
        item_id = _normalize(item)["id"]
        items = [item] + [x for x in items if _normalize(x)["id"] != item_id]
        write_jsonl(_queue_file(), items)
    _last_action = None
    return {"undone": {"type": action["type"], "item": _normalize(item)}}

@router.get("/config/labels")
def get_labels():
    return _LABEL_META

@router.get("/config")
def get_config():
    f = _config_file()
    if not f.exists():
        return {"accounts": [], "max_per_account": 500}
    raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return {"accounts": raw.get("accounts", []), "max_per_account": raw.get("max_per_account", 500)}

class ConfigPayload(BaseModel):
    accounts: list[dict]
    max_per_account: int = 500

@router.post("/config")
def post_config(payload: ConfigPayload):
    f = _config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(yaml.dump(payload.model_dump(), allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    tmp.rename(f)
    return {"ok": True}

@router.get("/stats")
def get_stats():
    records = read_jsonl(_score_file())
    counts: dict[str, int] = {}
    for r in records:
        lbl = r.get("label", "")
        if lbl:
            counts[lbl] = counts.get(lbl, 0) + 1
    benchmark_results: dict = {}
    benchmark_path = _DATA_DIR / "benchmark_results.json"
    if benchmark_path.exists():
        try:
            benchmark_results = json.loads(benchmark_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "total": len(records),
        "counts": counts,
        "score_file_bytes": _score_file().stat().st_size if _score_file().exists() else 0,
        "benchmark_results": benchmark_results,
    }

@router.get("/stats/download")
def download_stats():
    if not _score_file().exists():
        raise HTTPException(404, "No score file")
    return FileResponse(
        str(_score_file()),
        filename="email_score.jsonl",
        media_type="application/jsonlines",
        headers={"Content-Disposition": 'attachment; filename="email_score.jsonl"'},
    )
