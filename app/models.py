"""Avocet — HF model lifecycle API.

Handles model metadata lookup, approval queue, download with progress,
and installed model management.

All endpoints are registered on `router` (a FastAPI APIRouter).
api.py includes this router with prefix="/api/models".

Module-level globals (_MODELS_DIR, _QUEUE_DIR) follow the same
testability pattern as sft.py — override them via set_models_dir() and
set_queue_dir() in test fixtures.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.utils import read_jsonl, write_jsonl

try:
    from huggingface_hub import snapshot_download
except ImportError:  # pragma: no cover
    snapshot_download = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_MODELS_DIR: Path = _ROOT / "models"
_QUEUE_DIR: Path = _ROOT / "data"

router = APIRouter()

# ── Download progress shared state ────────────────────────────────────────────
# Updated by the background download thread; read by GET /download/stream.
_download_progress: dict[str, Any] = {}

# ── HF pipeline_tag → adapter recommendation ──────────────────────────────────
_TAG_TO_ADAPTER: dict[str, str] = {
    "zero-shot-classification": "ZeroShotAdapter",
    "text-classification": "ZeroShotAdapter",
    "natural-language-inference": "ZeroShotAdapter",
    "sentence-similarity": "RerankerAdapter",
    "text-ranking": "RerankerAdapter",
    "text-generation": "GenerationAdapter",
    "text2text-generation": "GenerationAdapter",
}


# ── Testability seams ──────────────────────────────────────────────────────────

def set_models_dir(path: Path) -> None:
    global _MODELS_DIR
    _MODELS_DIR = path


def set_queue_dir(path: Path) -> None:
    global _QUEUE_DIR
    _QUEUE_DIR = path


# ── Internal helpers ───────────────────────────────────────────────────────────

def _queue_file() -> Path:
    return _QUEUE_DIR / "model_queue.jsonl"


def _read_queue() -> list[dict]:
    return read_jsonl(_queue_file())


def _write_queue(records: list[dict]) -> None:
    write_jsonl(_queue_file(), records)


def _safe_model_name(repo_id: str) -> str:
    """Convert repo_id to a filesystem-safe directory name (HF convention)."""
    return repo_id.replace("/", "--")


def _is_installed(repo_id: str) -> bool:
    """Check if a model is already downloaded in _MODELS_DIR."""
    safe_name = _safe_model_name(repo_id)
    model_dir = _MODELS_DIR / safe_name
    return model_dir.exists() and (
        (model_dir / "config.json").exists()
        or (model_dir / "training_info.json").exists()
        or (model_dir / "model_info.json").exists()
    )


def _is_queued(repo_id: str) -> bool:
    """Check if repo_id is already in the queue (non-dismissed)."""
    for entry in _read_queue():
        if entry.get("repo_id") == repo_id and entry.get("status") != "dismissed":
            return True
    return False


def _update_queue_entry(entry_id: str, updates: dict) -> dict | None:
    """Update a queue entry by id. Returns updated entry or None if not found."""
    records = _read_queue()
    for i, r in enumerate(records):
        if r.get("id") == entry_id:
            records[i] = {**r, **updates}
            _write_queue(records)
            return records[i]
    return None


def _get_queue_entry(entry_id: str) -> dict | None:
    for r in _read_queue():
        if r.get("id") == entry_id:
            return r
    return None


# ── Background download ────────────────────────────────────────────────────────

def _run_download(entry_id: str, repo_id: str, pipeline_tag: str | None, adapter_recommendation: str | None) -> None:
    """Background thread: download model via huggingface_hub.snapshot_download."""
    global _download_progress
    safe_name = _safe_model_name(repo_id)
    local_dir = _MODELS_DIR / safe_name

    _download_progress = {
        "active": True,
        "repo_id": repo_id,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "pct": 0.0,
        "done": False,
        "error": None,
    }

    try:
        if snapshot_download is None:
            raise RuntimeError("huggingface_hub is not installed")

        snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
        )

        # Write model_info.json alongside downloaded files
        model_info = {
            "repo_id": repo_id,
            "pipeline_tag": pipeline_tag,
            "adapter_recommendation": adapter_recommendation,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "model_info.json").write_text(
            json.dumps(model_info, indent=2), encoding="utf-8"
        )

        _download_progress["done"] = True
        _download_progress["pct"] = 100.0
        _update_queue_entry(entry_id, {"status": "ready"})

    except Exception as exc:
        logger.exception("Download failed for %s: %s", repo_id, exc)
        _download_progress["error"] = str(exc)
        _download_progress["done"] = True
        _update_queue_entry(entry_id, {"status": "failed", "error": str(exc)})
    finally:
        _download_progress["active"] = False


# ── GET /lookup ────────────────────────────────────────────────────────────────

@router.get("/lookup")
def lookup_model(repo_id: str) -> dict:
    """Validate repo_id and fetch metadata from the HF API."""
    # Validate: must contain exactly one '/', no whitespace
    if "/" not in repo_id or any(c.isspace() for c in repo_id):
        raise HTTPException(422, f"Invalid repo_id {repo_id!r}: must be 'owner/model-name' with no whitespace")

    hf_url = f"https://huggingface.co/api/models/{repo_id}"
    try:
        resp = httpx.get(hf_url, timeout=10.0)
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Network error reaching HuggingFace API: {exc}") from exc

    if resp.status_code == 404:
        raise HTTPException(404, f"Model {repo_id!r} not found on HuggingFace")
    if resp.status_code != 200:
        raise HTTPException(502, f"HuggingFace API returned status {resp.status_code}")

    data = resp.json()
    pipeline_tag = data.get("pipeline_tag")
    adapter_recommendation = _TAG_TO_ADAPTER.get(pipeline_tag) if pipeline_tag else None
    if pipeline_tag and adapter_recommendation is None:
        logger.warning("Unknown pipeline_tag %r for %s — no adapter recommendation", pipeline_tag, repo_id)

    # Estimate model size from siblings list
    siblings = data.get("siblings") or []
    model_size_bytes: int = sum(s.get("size", 0) for s in siblings if isinstance(s, dict))

    # Description: first 300 chars of card data (modelId field used as fallback)
    card_data = data.get("cardData") or {}
    description_raw = card_data.get("description") or data.get("modelId") or ""
    description = description_raw[:300] if description_raw else ""

    return {
        "repo_id": repo_id,
        "pipeline_tag": pipeline_tag,
        "adapter_recommendation": adapter_recommendation,
        "model_size_bytes": model_size_bytes,
        "description": description,
        "tags": data.get("tags") or [],
        "downloads": data.get("downloads") or 0,
        "already_installed": _is_installed(repo_id),
        "already_queued": _is_queued(repo_id),
    }


# ── GET /queue ─────────────────────────────────────────────────────────────────

@router.get("/queue")
def get_queue() -> list[dict]:
    """Return all non-dismissed queue entries sorted newest-first."""
    records = _read_queue()
    active = [r for r in records if r.get("status") != "dismissed"]
    return sorted(active, key=lambda r: r.get("queued_at", ""), reverse=True)


# ── POST /queue ────────────────────────────────────────────────────────────────

class QueueAddRequest(BaseModel):
    repo_id: str
    pipeline_tag: str | None = None
    adapter_recommendation: str | None = None


@router.post("/queue", status_code=201)
def add_to_queue(req: QueueAddRequest) -> dict:
    """Add a model to the approval queue with status 'pending'."""
    if _is_installed(req.repo_id):
        raise HTTPException(409, f"{req.repo_id!r} is already installed")
    if _is_queued(req.repo_id):
        raise HTTPException(409, f"{req.repo_id!r} is already in the queue")

    entry = {
        "id": str(uuid4()),
        "repo_id": req.repo_id,
        "pipeline_tag": req.pipeline_tag,
        "adapter_recommendation": req.adapter_recommendation,
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    records = _read_queue()
    records.append(entry)
    _write_queue(records)
    return entry


# ── POST /queue/{id}/approve ───────────────────────────────────────────────────

@router.post("/queue/{entry_id}/approve")
def approve_queue_entry(entry_id: str) -> dict:
    """Approve a pending queue entry and start background download."""
    entry = _get_queue_entry(entry_id)
    if entry is None:
        raise HTTPException(404, f"Queue entry {entry_id!r} not found")
    if entry.get("status") != "pending":
        raise HTTPException(409, f"Entry is not in pending state (current: {entry.get('status')!r})")

    updated = _update_queue_entry(entry_id, {"status": "downloading"})

    thread = threading.Thread(
        target=_run_download,
        args=(entry_id, entry["repo_id"], entry.get("pipeline_tag"), entry.get("adapter_recommendation")),
        daemon=True,
        name=f"model-download-{entry_id}",
    )
    thread.start()

    return {"ok": True}


# ── DELETE /queue/{id} ─────────────────────────────────────────────────────────

@router.delete("/queue/{entry_id}")
def dismiss_queue_entry(entry_id: str) -> dict:
    """Dismiss (soft-delete) a queue entry."""
    entry = _get_queue_entry(entry_id)
    if entry is None:
        raise HTTPException(404, f"Queue entry {entry_id!r} not found")

    _update_queue_entry(entry_id, {"status": "dismissed"})
    return {"ok": True}


# ── GET /download/stream ───────────────────────────────────────────────────────

@router.get("/download/stream")
def download_stream() -> StreamingResponse:
    """SSE stream of download progress. Yields one idle event if no download active."""

    def generate():
        prog = _download_progress
        if not prog.get("active") and not (prog.get("done") and not prog.get("error")):
            yield f"data: {json.dumps({'type': 'idle'})}\n\n"
            return

        if prog.get("done"):
            if prog.get("error"):
                yield f"data: {json.dumps({'type': 'error', 'error': prog['error']})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'done', 'repo_id': prog.get('repo_id')})}\n\n"
            return

        # Stream live progress
        import time
        while True:
            p = dict(_download_progress)
            if p.get("done"):
                if p.get("error"):
                    yield f"data: {json.dumps({'type': 'error', 'error': p['error']})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'done', 'repo_id': p.get('repo_id')})}\n\n"
                break
            event = json.dumps({
                "type": "progress",
                "repo_id": p.get("repo_id"),
                "downloaded_bytes": p.get("downloaded_bytes", 0),
                "total_bytes": p.get("total_bytes", 0),
                "pct": p.get("pct", 0.0),
            })
            yield f"data: {event}\n\n"
            time.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── GET /installed ─────────────────────────────────────────────────────────────

@router.get("/installed")
def list_installed() -> list[dict]:
    """Scan _MODELS_DIR and return info on each installed model."""
    if not _MODELS_DIR.exists():
        return []

    results: list[dict] = []
    for sub in _MODELS_DIR.iterdir():
        if not sub.is_dir():
            continue

        has_training_info = (sub / "training_info.json").exists()
        has_config = (sub / "config.json").exists()
        has_model_info = (sub / "model_info.json").exists()

        if not (has_training_info or has_config or has_model_info):
            continue

        model_type = "finetuned" if has_training_info else "downloaded"

        # Compute directory size
        size_bytes = sum(f.stat().st_size for f in sub.rglob("*") if f.is_file())

        # Load adapter/model_id from model_info.json or training_info.json
        adapter: str | None = None
        model_id: str | None = None

        if has_model_info:
            try:
                info = json.loads((sub / "model_info.json").read_text(encoding="utf-8"))
                adapter = info.get("adapter_recommendation")
                model_id = info.get("repo_id")
            except Exception:
                pass
        elif has_training_info:
            try:
                info = json.loads((sub / "training_info.json").read_text(encoding="utf-8"))
                adapter = info.get("adapter")
                model_id = info.get("base_model") or info.get("model_id")
            except Exception:
                pass

        results.append({
            "name": sub.name,
            "path": str(sub),
            "type": model_type,
            "adapter": adapter,
            "size_bytes": size_bytes,
            "model_id": model_id,
        })

    return results


# ── DELETE /installed/{name} ───────────────────────────────────────────────────

@router.delete("/installed/{name}")
def delete_installed(name: str) -> dict:
    """Remove an installed model directory by name. Blocks path traversal."""
    # Validate: single path component, no slashes or '..'
    if "/" in name or "\\" in name or ".." in name or not name or name.startswith("."):
        raise HTTPException(400, f"Invalid model name {name!r}: must be a single directory name with no path separators or '..'")

    model_path = _MODELS_DIR / name

    # Extra safety: confirm resolved path is inside _MODELS_DIR
    try:
        model_path.resolve().relative_to(_MODELS_DIR.resolve())
    except ValueError:
        raise HTTPException(400, f"Path traversal detected for name {name!r}")

    if not model_path.exists():
        raise HTTPException(404, f"Installed model {name!r} not found")

    shutil.rmtree(model_path)
    return {"ok": True}
