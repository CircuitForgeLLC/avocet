"""Avocet — Log Corpus receiver and labeling API.

Receives push batches from consented Turnstone nodes, stores entries for labeling,
and exports labeled data as JSONL for the logreading fine-tune pipeline.

DB: data/corpus.db (separate from train_jobs.db — different lifecycle)
Auth: Bearer token validated against corpus_sources table (seeded from label_tool.yaml).

All endpoints registered on `router`. api.py includes this with prefix="/api/corpus".
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.requests import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent
_CONFIG_DIR: Path | None = None
_DATA_DIR: Path = _ROOT / "data"

router = APIRouter()

_DB_PATH: Path = _ROOT / "data" / "corpus.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_sources (
    token           TEXT PRIMARY KEY,
    source_host     TEXT NOT NULL,
    owner           TEXT NOT NULL,
    consent_date    TEXT NOT NULL,
    consent_method  TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS corpus_batches (
    id              TEXT PRIMARY KEY,
    source_host     TEXT NOT NULL,
    batch_type      TEXT NOT NULL,
    received_at     TEXT NOT NULL,
    entry_count     INTEGER NOT NULL,
    watermark_from  TEXT,
    watermark_to    TEXT,
    raw_json        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_entries (
    id                  TEXT PRIMARY KEY,
    batch_id            TEXT NOT NULL REFERENCES corpus_batches(id),
    source_host         TEXT NOT NULL,
    origin_entry_id     TEXT,
    timestamp_iso       TEXT,
    severity            TEXT,
    source_id           TEXT,
    text                TEXT NOT NULL,
    matched_patterns    TEXT DEFAULT '[]',
    label_state         TEXT NOT NULL DEFAULT 'unlabeled',
    failure_type        TEXT,
    plain_explanation   TEXT,
    known_pattern       TEXT,
    labeled_at          TEXT,
    labeled_by          TEXT DEFAULT 'alan',
    pii_flagged         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ce_label_state ON corpus_entries(label_state);
CREATE INDEX IF NOT EXISTS idx_ce_source      ON corpus_entries(source_host);
CREATE INDEX IF NOT EXISTS idx_ce_severity    ON corpus_entries(severity);
"""


# ── Testability seams ──────────────────────────────────────────────────────────

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path


def set_data_dir(path: Path) -> None:
    global _DATA_DIR, _DB_PATH
    _DATA_DIR = path
    _DB_PATH = path / "corpus.db"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


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
        _seed_sources(conn)


def _load_corpus_config() -> list[dict]:
    f = _config_file()
    if not f.exists():
        return []
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse corpus config: %s", exc)
        return []
    return raw.get("corpus", {}).get("sources", []) or []


def _seed_sources(conn: sqlite3.Connection) -> None:
    for src in _load_corpus_config():
        conn.execute(
            "INSERT OR IGNORE INTO corpus_sources (token, source_host, owner, consent_date, consent_method) "
            "VALUES (?, ?, ?, ?, ?)",
            (src["token"], src["source_host"], src["owner"],
             src["consent_date"], src["consent_method"]),
        )


def _validate_token(token: str, conn: sqlite3.Connection) -> str:
    """Return source_host for token, or raise 403."""
    row = conn.execute(
        "SELECT source_host FROM corpus_sources WHERE token = ? AND active = 1",
        (token,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=403, detail="Unknown or revoked consent token")
    return row["source_host"]


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    return auth.removeprefix("Bearer ").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Startup ────────────────────────────────────────────────────────────────────

_init_db()


# ── POST /api/corpus/log-batch ─────────────────────────────────────────────────

@router.post("/log-batch")
def receive_batch(request: Request, payload: dict) -> dict:
    """Accept a push batch from a Turnstone node."""
    token = _extract_bearer(request)

    batch_type = payload.get("batch_type", "raw_entries")
    entries_raw = payload.get("entries", [])
    batch_id = payload.get("batch_id") or str(uuid.uuid4())

    with _db() as conn:
        source_host = _validate_token(token, conn)

        conn.execute(
            "INSERT INTO corpus_batches (id, source_host, batch_type, received_at, entry_count, "
            "watermark_from, watermark_to, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (batch_id, source_host, batch_type, _now_iso(), len(entries_raw),
             str(payload.get("watermark_from", "")),
             str(payload.get("watermark_to", "")),
             json.dumps(payload)),
        )

        stored = 0
        for entry in entries_raw:
            text = entry.get("text", "").strip()
            if not text:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO corpus_entries "
                "(id, batch_id, source_host, origin_entry_id, timestamp_iso, severity, "
                "source_id, text, matched_patterns) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), batch_id, source_host,
                 entry.get("entry_id") or entry.get("id"),
                 entry.get("timestamp_iso"),
                 entry.get("severity"),
                 entry.get("source_id"),
                 text,
                 json.dumps(entry.get("matched_patterns", []))),
            )
            stored += 1

    logger.info("Received batch %s from %s: %d/%d entries stored",
                batch_id, source_host, stored, len(entries_raw))
    return {"received": True, "batch_id": batch_id, "entries_stored": stored}


# ── GET /api/corpus/entries ────────────────────────────────────────────────────

@router.get("/entries")
def list_entries(
    state: str = "unlabeled",
    source_host: str | None = None,
    limit: int = 25,
) -> dict:
    """Return entries for labeling. Default: unlabeled entries, oldest first."""
    with _db() as conn:
        query = "SELECT * FROM corpus_entries WHERE label_state = ?"
        params: list = [state]
        if source_host:
            query += " AND source_host = ?"
            params.append(source_host)
        query += " ORDER BY rowid LIMIT ?"
        params.append(min(limit, 100))
        rows = conn.execute(query, params).fetchall()
    return {"entries": [dict(r) for r in rows], "count": len(rows)}


# ── POST /api/corpus/entries/{id}/label ───────────────────────────────────────

@router.post("/entries/{entry_id}/label")
def label_entry(entry_id: str, body: dict) -> dict:
    """Submit a label for a corpus entry."""
    failure_type = body.get("failure_type")
    plain_explanation = body.get("plain_explanation", "").strip()
    known_pattern = body.get("known_pattern")
    pii_flagged = int(bool(body.get("pii_flagged", False)))

    if not failure_type:
        raise HTTPException(status_code=422, detail="failure_type is required")
    valid_types = {"hardware", "software", "network", "security", "application", "none", "other"}
    if failure_type not in valid_types:
        raise HTTPException(status_code=422, detail=f"failure_type must be one of {sorted(valid_types)}")

    with _db() as conn:
        row = conn.execute("SELECT id FROM corpus_entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        conn.execute(
            "UPDATE corpus_entries SET label_state='labeled', failure_type=?, plain_explanation=?, "
            "known_pattern=?, labeled_at=?, pii_flagged=? WHERE id=?",
            (failure_type, plain_explanation, known_pattern, _now_iso(), pii_flagged, entry_id),
        )
    return {"labeled": True, "entry_id": entry_id}


# ── POST /api/corpus/entries/{id}/skip ────────────────────────────────────────

@router.post("/entries/{entry_id}/skip")
def skip_entry(entry_id: str) -> dict:
    with _db() as conn:
        row = conn.execute("SELECT id FROM corpus_entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        conn.execute(
            "UPDATE corpus_entries SET label_state='skipped' WHERE id=?", (entry_id,)
        )
    return {"skipped": True, "entry_id": entry_id}


# ── GET /api/corpus/stats ──────────────────────────────────────────────────────

@router.get("/stats")
def get_stats() -> dict:
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM corpus_entries").fetchone()[0]
        by_state = {
            r["label_state"]: r["cnt"]
            for r in conn.execute(
                "SELECT label_state, COUNT(*) AS cnt FROM corpus_entries GROUP BY label_state"
            ).fetchall()
        }
        by_source = {
            r["source_host"]: r["cnt"]
            for r in conn.execute(
                "SELECT source_host, COUNT(*) AS cnt FROM corpus_entries GROUP BY source_host"
            ).fetchall()
        }
        by_severity = {
            r["severity"]: r["cnt"]
            for r in conn.execute(
                "SELECT severity, COUNT(*) AS cnt FROM corpus_entries "
                "WHERE severity IS NOT NULL GROUP BY severity"
            ).fetchall()
        }
        batch_count = conn.execute("SELECT COUNT(*) FROM corpus_batches").fetchone()[0]
    return {
        "total_entries": total,
        "batch_count": batch_count,
        "by_label_state": by_state,
        "by_source": by_source,
        "by_severity": by_severity,
    }


# ── GET /api/corpus/export ────────────────────────────────────────────────────

@router.get("/export")
def export_labeled() -> StreamingResponse:
    """Stream labeled, non-PII entries as JSONL for SFT harness."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT source_host, source_id, severity, text, failure_type, plain_explanation, known_pattern "
            "FROM corpus_entries "
            "WHERE label_state = 'labeled' AND pii_flagged = 0 AND plain_explanation != ''"
            "ORDER BY rowid"
        ).fetchall()

    def _generate():
        for row in rows:
            record = {
                "input": row["text"],
                "output": row["plain_explanation"],
                "metadata": {
                    "failure_type": row["failure_type"],
                    "source": row["source_host"],
                    "source_id": row["source_id"],
                    "severity": row["severity"],
                    "known_pattern": row["known_pattern"],
                },
            }
            yield json.dumps(record) + "\n"

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=log_corpus_labeled.jsonl"},
    )
