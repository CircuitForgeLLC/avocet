"""Avocet — FastAPI REST layer.

JSONL read/write helpers and FastAPI app instance.
Endpoints and static file serving are added in subsequent tasks.
"""
from __future__ import annotations

import json
from pathlib import Path

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

_ROOT = Path(__file__).parent.parent
_DATA_DIR: Path = _ROOT / "data"   # overridable in tests via set_data_dir()


def set_data_dir(path: Path) -> None:
    """Override data directory — used by tests."""
    global _DATA_DIR
    _DATA_DIR = path


def reset_last_action() -> None:
    """Reset undo state — used by tests."""
    global _last_action
    _last_action = None


def _queue_file() -> Path:
    return _DATA_DIR / "email_label_queue.jsonl"


def _score_file() -> Path:
    return _DATA_DIR / "email_score.jsonl"


def _discarded_file() -> Path:
    return _DATA_DIR / "discarded.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    path.write_text(text + "\n" if records else "", encoding="utf-8")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


app = FastAPI(title="Avocet API")

# In-memory last-action store (single user, local tool — in-memory is fine)
_last_action: dict | None = None


@app.get("/api/queue")
def get_queue(limit: int = Query(default=10, ge=1, le=50)):
    items = _read_jsonl(_queue_file())
    return {"items": items[:limit], "total": len(items)}


class LabelRequest(BaseModel):
    id: str
    label: str


@app.post("/api/label")
def post_label(req: LabelRequest):
    global _last_action
    items = _read_jsonl(_queue_file())
    match = next((x for x in items if x["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    record = {**match, "label": req.label,
              "labeled_at": datetime.now(timezone.utc).isoformat()}
    _append_jsonl(_score_file(), record)
    _write_jsonl(_queue_file(), [x for x in items if x["id"] != req.id])
    _last_action = {"type": "label", "item": match, "label": req.label}
    return {"ok": True}


class SkipRequest(BaseModel):
    id: str


@app.post("/api/skip")
def post_skip(req: SkipRequest):
    global _last_action
    items = _read_jsonl(_queue_file())
    match = next((x for x in items if x["id"] == req.id), None)
    if not match:
        raise HTTPException(404, f"Item {req.id!r} not found in queue")
    reordered = [x for x in items if x["id"] != req.id] + [match]
    _write_jsonl(_queue_file(), reordered)
    _last_action = {"type": "skip", "item": match}
    return {"ok": True}
