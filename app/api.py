"""Avocet — FastAPI REST layer.

JSONL read/write helpers and FastAPI app instance.
Endpoints and static file serving are added in subsequent tasks.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess as _subprocess
import yaml
from pathlib import Path

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

_ROOT = Path(__file__).parent.parent
_DATA_DIR: Path = _ROOT / "data"     # overridable in tests via set_data_dir()
_MODELS_DIR: Path = _ROOT / "models" # overridable in tests via set_models_dir()
_CONFIG_DIR: Path | None = None      # None = use real path


def set_data_dir(path: Path) -> None:
    """Override data directory — used by tests."""
    global _DATA_DIR
    _DATA_DIR = path


def set_models_dir(path: Path) -> None:
    """Override models directory — used by tests."""
    global _MODELS_DIR
    _MODELS_DIR = path


def set_config_dir(path: Path | None) -> None:
    """Override config directory — used by tests."""
    global _CONFIG_DIR
    _CONFIG_DIR = path


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


def _item_id(item: dict) -> str:
    """Stable content-hash ID — matches label_tool.py _entry_key dedup logic."""
    key = (item.get("subject", "") + (item.get("body", "") or "")[:100])
    return hashlib.md5(key.encode("utf-8", errors="replace")).hexdigest()


def _normalize(item: dict) -> dict:
    """Normalize JSONL item to the Vue frontend schema.

    label_tool.py stores: subject, body, from_addr, date, account (no id).
    The Vue app expects: id, subject, body, from, date, source.
    Both old (from_addr/account) and new (from/source) field names are handled.
    """
    return {
        "id":      item.get("id") or _item_id(item),
        "subject": item.get("subject", ""),
        "body":    item.get("body", ""),
        "from":    item.get("from") or item.get("from_addr", ""),
        "date":    item.get("date", ""),
        "source":  item.get("source") or item.get("account", ""),
    }


app = FastAPI(title="Avocet API")

from app.data.label import router as label_router
app.include_router(label_router, prefix="/api")

from app.sft import router as sft_router
app.include_router(sft_router, prefix="/api/sft")

from app.models import router as models_router
import app.models as _models_module
app.include_router(models_router, prefix="/api/models")

from app.eval.cforch import router as eval_router
app.include_router(eval_router, prefix="/api")

from app.imitate import router as imitate_router
app.include_router(imitate_router, prefix="/api/imitate")

from app.data.fetch import router as fetch_router
app.include_router(fetch_router, prefix="/api")

from app.train.train import router as train_router
app.include_router(train_router, prefix="/api/train")


# Static SPA — MUST be last (catches all unmatched paths)
_DIST = _ROOT / "web" / "dist"
if _DIST.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Serve index.html with no-cache so browsers always fetch fresh HTML after rebuilds.
    # Hashed assets (/assets/index-abc123.js) can be cached forever — they change names
    # when content changes (standard Vite cache-busting strategy).
    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}

    @app.get("/")
    def get_spa_root():
        return FileResponse(str(_DIST / "index.html"), headers=_NO_CACHE)

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="spa")
