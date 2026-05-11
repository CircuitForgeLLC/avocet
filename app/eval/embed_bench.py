"""Avocet — embedding model comparison harness.

Exposes FastAPI routes under /api/embed-bench (mounted via app/eval/cforch.py).
All computation is local: no LLM inference, Ollama only. MIT tier throughout.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent
_CONFIG_DIR: Path | None = None   # override via set_config_dir() in tests
_RUN_ACTIVE: bool = False
_RATINGS_FILE = _ROOT / "data" / "embed_bench_ratings.jsonl"

router = APIRouter()


# ── Testability seam ──────────────────────────────────────────────────────────

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path


# ── Internal helpers ──────────────────────────────────────────────────────────

def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def _load_config() -> dict[str, Any]:
    f = _config_file()
    if not f.exists():
        return {}
    try:
        return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse embed_bench config %s: %s", f, exc)
        return {}


def _ollama_url() -> str:
    cfg = _load_config()
    embed_cfg = cfg.get("embed_bench", {}) or {}
    cforch_cfg = cfg.get("cforch", {}) or {}
    return (
        embed_cfg.get("ollama_url")
        or cforch_cfg.get("ollama_url", "http://localhost:11434")
    )


def _ratings_path() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "embed_bench_ratings.jsonl"
    return _RATINGS_FILE


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(
            f"Embedding dimension mismatch: {len(a)} vs {len(b)}"
        )
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── GET /models ───────────────────────────────────────────────────────────────

@router.get("/models")
def get_models() -> dict:
    """Return Ollama embedding models available on the configured instance."""
    ollama = _ollama_url()
    models: list[dict] = []
    try:
        resp = httpx.get(f"{ollama}/api/tags", timeout=5.0)
        resp.raise_for_status()
        for entry in resp.json().get("models", []):
            models.append({
                "name": entry.get("name", ""),
                "size": entry.get("size", 0),
            })
    except httpx.HTTPStatusError as exc:
        logger.warning("Ollama /api/tags returned HTTP %s: %s", exc.response.status_code, exc)
    except httpx.RequestError as exc:
        logger.warning("Failed to reach Ollama for model list: %s", exc)
    return {"models": models, "ollama_url": ollama}


# ── POST /run ─────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    corpus: list[str]
    queries: list[str]
    models: list[str]
    top_k: int = 5
    ollama_url: str = ""

    @field_validator("corpus")
    @classmethod
    def corpus_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("corpus must not be empty")
        return v

    @field_validator("queries")
    @classmethod
    def queries_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("queries must not be empty")
        return v

    @field_validator("models")
    @classmethod
    def models_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("models must contain at least one model name")
        return v


def _embed_texts(ollama: str, model: str, texts: list[str]) -> list[list[float]]:
    """Batch-embed texts via Ollama /v1/embeddings. Returns one vector per text."""
    resp = httpx.post(
        f"{ollama}/v1/embeddings",
        json={"model": model, "input": texts},
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [item["embedding"] for item in data]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/run")
def run_embed_bench(req: RunRequest) -> StreamingResponse:
    """Embed corpus + queries with each model; stream SSE results."""
    global _RUN_ACTIVE

    if _RUN_ACTIVE:
        raise HTTPException(409, "An embedding benchmark run is already active")

    ollama = req.ollama_url or _ollama_url()

    def _generate():
        global _RUN_ACTIVE
        _RUN_ACTIVE = True
        try:
            for model_idx, model in enumerate(req.models, start=1):
                yield _sse({
                    "type": "progress",
                    "msg": f"Indexing corpus with {model} ({model_idx}/{len(req.models)})...",
                })
                try:
                    corpus_vecs = _embed_texts(ollama, model, req.corpus)
                except Exception as exc:
                    yield _sse({"type": "error", "msg": f"Ollama error for {model}: {exc}"})
                    continue

                yield _sse({
                    "type": "progress",
                    "msg": f"Running queries with {model}...",
                })

                for q_idx, query in enumerate(req.queries):
                    try:
                        q_vecs = _embed_texts(ollama, model, [query])
                    except Exception as exc:
                        yield _sse({"type": "error", "msg": f"Query embed error ({model}): {exc}"})
                        continue
                    q_vec = q_vecs[0]
                    scored = sorted(
                        [
                            {"chunk_idx": i, "text": chunk, "score": round(_cosine(q_vec, cv), 4)}
                            for i, (chunk, cv) in enumerate(zip(req.corpus, corpus_vecs))
                        ],
                        key=lambda h: h["score"],
                        reverse=True,
                    )[: req.top_k]
                    yield _sse({
                        "type": "result",
                        "query_idx": q_idx,
                        "query": query,
                        "model": model,
                        "hits": scored,
                    })

            yield _sse({"type": "done"})
        finally:
            _RUN_ACTIVE = False

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ── POST /rate ────────────────────────────────────────────────────────────────

_VALID_RATINGS = {"relevant", "not_relevant"}


class RatingRequest(BaseModel):
    query: str
    model: str
    chunk_text: str
    chunk_idx: int
    rating: str

    @field_validator("rating")
    @classmethod
    def rating_valid(cls, v: str) -> str:
        if v not in _VALID_RATINGS:
            raise ValueError(f"rating must be one of {_VALID_RATINGS}")
        return v


@router.post("/rate")
def rate_result(req: RatingRequest) -> dict:
    """Append one rating to the JSONL ratings file."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": req.query,
        "model": req.model,
        "chunk_idx": req.chunk_idx,
        "chunk_text": req.chunk_text,
        "rating": req.rating,
    }
    path = _ratings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return {"ok": True}


# ── GET /export ───────────────────────────────────────────────────────────────

_CSV_FIELDS = ["timestamp", "query", "model", "chunk_idx", "chunk_text", "rating"]


@router.get("/export")
def export_ratings(format: str = "csv") -> Any:
    """Download ratings as CSV or JSON."""
    path = _ratings_path()
    rows: list[dict] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if raw:
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="embed_comparison_{date_str}.json"'},
        )

    # Default: CSV
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="embed_comparison_{date_str}.csv"'},
    )
