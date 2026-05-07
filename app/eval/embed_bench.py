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
