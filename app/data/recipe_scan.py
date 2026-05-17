"""Avocet — Recipe scan labeling API (avocet#65).

Receives recipe scan items from the Kiwi pipeline (scanner/phone image +
docuvision OCR extraction + ground-truth structured recipe), presents them
for human review, and exports approved/edited pairs in the messages chat
format for the vision fine-tune harness.

DB: data/recipe_scan.db (separate from corpus.db — different lifecycle)
No auth required — local admin tool, not a push endpoint.

All endpoints registered on `router`. api.py includes this with
prefix="/api/recipe-scan".
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent
_DB_PATH: Path = _ROOT / "data" / "recipe_scan.db"

_VALID_MODALITIES = {"scanner", "phone", "handwritten"}
_VALID_STATUSES = {"pending", "approved", "edited", "rejected"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe_scan_items (
    id              TEXT PRIMARY KEY,
    image_path      TEXT NOT NULL,
    modality        TEXT NOT NULL DEFAULT 'scanner',
    source          TEXT NOT NULL DEFAULT 'purple_carrot',
    extracted       TEXT NOT NULL,
    ground_truth    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    corrected       TEXT,
    labeled_at      TEXT,
    rejected_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_rsi_status   ON recipe_scan_items(status);
CREATE INDEX IF NOT EXISTS idx_rsi_modality ON recipe_scan_items(modality);
"""

router = APIRouter()


# ── Testability seam ──────────────────────────────────────────────────────────

def set_db_path(path: Path) -> None:
    global _DB_PATH
    _DB_PATH = path


# ── Internal helpers ──────────────────────────────────────────────────────────

@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db() -> None:
    with _db() as conn:
        conn.executescript(_SCHEMA)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_training_pair(row: sqlite3.Row) -> dict:
    """Build a messages-format training pair from a labeled row.

    user message: correction prompt + the docuvision-extracted JSON draft.
    Trains the model to review and correct an existing extraction, which is
    more data-efficient than producing from scratch when OCR is usually close.

    assistant message: the approved ground truth (or human-corrected JSON).
    """
    target_str = row["corrected"] if row["corrected"] else row["ground_truth"]
    extracted = json.loads(row["extracted"])
    target = json.loads(target_str)
    user_content = (
        "Review and correct this recipe extraction. "
        "Return valid JSON with fields: title, description, ingredients, steps, "
        "prep_time, cook_time, servings.\n\n"
        f"Extraction to review:\n{json.dumps(extracted, ensure_ascii=False, indent=2)}"
    )
    return {
        "id": row["id"],
        "modality": row["modality"],
        "source": row["source"],
        "image_path": row["image_path"],
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ],
    }


_init_db()


# ── POST /import ───────────────────────────────────────────────────────────────

class ImportItem(BaseModel):
    id: str = ""
    image_path: str
    modality: Literal["scanner", "phone", "handwritten"] = "scanner"
    source: str = "purple_carrot"
    extracted: dict
    ground_truth: dict

    @field_validator("id", mode="before")
    @classmethod
    def default_id(cls, v: str) -> str:
        return v or str(uuid.uuid4())


class ImportRequest(BaseModel):
    items: list[ImportItem]


@router.post("/import")
def import_items(body: ImportRequest) -> dict:
    """Bulk-import scan items from the Kiwi pipeline. Idempotent by item id."""
    stored = 0
    with _db() as conn:
        for item in body.items:
            result = conn.execute(
                "INSERT OR IGNORE INTO recipe_scan_items "
                "(id, image_path, modality, source, extracted, ground_truth) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item.id, item.image_path, item.modality, item.source,
                 json.dumps(item.extracted), json.dumps(item.ground_truth)),
            )
            stored += result.rowcount
    return {"imported": stored, "total_submitted": len(body.items)}


# ── GET /next ─────────────────────────────────────────────────────────────────

@router.get("/next")
def get_next() -> dict:
    """Return the next pending item for review, oldest-first."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM recipe_scan_items WHERE status = 'pending' ORDER BY rowid LIMIT 1"
        ).fetchone()
    if row is None:
        raise HTTPException(404, "No pending items in queue")
    return {
        **dict(row),
        "extracted": json.loads(row["extracted"]),
        "ground_truth": json.loads(row["ground_truth"]),
    }


# ── POST /items/{id}/approve ──────────────────────────────────────────────────

@router.post("/items/{item_id}/approve")
def approve_item(item_id: str) -> dict:
    """Mark item as approved — extracted JSON is close enough to ground truth."""
    with _db() as conn:
        row = conn.execute("SELECT id FROM recipe_scan_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Item not found")
        conn.execute(
            "UPDATE recipe_scan_items SET status='approved', labeled_at=? WHERE id=?",
            (_now_iso(), item_id),
        )
    return {"status": "approved", "id": item_id}


# ── POST /items/{id}/edit ─────────────────────────────────────────────────────

class EditBody(BaseModel):
    corrected: dict


@router.post("/items/{item_id}/edit")
def edit_item(item_id: str, body: EditBody) -> dict:
    """Approve with a human-corrected JSON. corrected overrides extracted in export."""
    with _db() as conn:
        row = conn.execute("SELECT id FROM recipe_scan_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Item not found")
        conn.execute(
            "UPDATE recipe_scan_items SET status='edited', corrected=?, labeled_at=? WHERE id=?",
            (json.dumps(body.corrected), _now_iso(), item_id),
        )
    return {"status": "edited", "id": item_id}


# ── POST /items/{id}/reject ───────────────────────────────────────────────────

class RejectBody(BaseModel):
    reason: str = ""


@router.post("/items/{item_id}/reject")
def reject_item(item_id: str, body: RejectBody = RejectBody()) -> dict:
    """Reject item — extraction too broken to use for training."""
    with _db() as conn:
        row = conn.execute("SELECT id FROM recipe_scan_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Item not found")
        conn.execute(
            "UPDATE recipe_scan_items SET status='rejected', rejected_reason=?, labeled_at=? WHERE id=?",
            (body.reason or None, _now_iso(), item_id),
        )
    return {"status": "rejected", "id": item_id}


# ── GET /stats ────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats() -> dict:
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM recipe_scan_items").fetchone()[0]
        by_status = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM recipe_scan_items GROUP BY status"
            ).fetchall()
        }
        by_modality = {
            r["modality"]: r["cnt"]
            for r in conn.execute(
                "SELECT modality, COUNT(*) AS cnt FROM recipe_scan_items GROUP BY modality"
            ).fetchall()
        }
        export_ready = conn.execute(
            "SELECT COUNT(*) FROM recipe_scan_items WHERE status IN ('approved', 'edited')"
        ).fetchone()[0]
    return {
        "total": total,
        "by_status": by_status,
        "by_modality": by_modality,
        "export_ready": export_ready,
    }


# ── GET /export ───────────────────────────────────────────────────────────────

@router.get("/export")
def export_pairs() -> StreamingResponse:
    """Stream approved/edited items as JSONL training pairs (messages format)."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM recipe_scan_items WHERE status IN ('approved', 'edited') ORDER BY rowid"
        ).fetchall()

    def _generate():
        for row in rows:
            yield json.dumps(_build_training_pair(row), ensure_ascii=False) + "\n"

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=recipe_scan_pairs.jsonl"},
    )


# ── GET /image ────────────────────────────────────────────────────────────────

_IMAGE_ROOT = Path("/Library/Assets/kiwi")


@router.get("/image")
def serve_image(path: str) -> StreamingResponse:
    """Serve a scan image from /Library/Assets/kiwi/.

    path must resolve within /Library/Assets/kiwi/ — rejects traversal attempts.
    """
    try:
        resolved = Path(path).resolve()
        _IMAGE_ROOT.resolve()  # ensure root itself is valid
        resolved.relative_to(_IMAGE_ROOT.resolve())
    except (ValueError, OSError):
        raise HTTPException(403, "Path outside allowed image directory")

    if not resolved.exists():
        raise HTTPException(404, "Image not found")

    suffix = resolved.suffix.lower()
    media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = media_types.get(suffix, "application/octet-stream")

    return StreamingResponse(
        open(resolved, "rb"),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
