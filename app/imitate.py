"""Avocet — Imitate tab API.

Fetches real samples from sibling CF product APIs, sends them through selected
local LLMs (ollama), and streams responses back to the UI. Results can be
pushed into the SFT corrections queue for human review.

All endpoints registered on `router`. api.py includes this with prefix="/api/imitate".

Module-level globals follow the same testability pattern as cforch.py and sft.py:
override _CONFIG_DIR and _DATA_DIR via set_config_dir() / set_data_dir() in tests.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.utils import append_jsonl

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_CONFIG_DIR: Path | None = None
_DATA_DIR: Path = _ROOT / "data"

router = APIRouter()


# ── Testability seams ──────────────────────────────────────────────────────────

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path


def set_data_dir(path: Path) -> None:
    global _DATA_DIR
    _DATA_DIR = path


# ── Internal helpers ───────────────────────────────────────────────────────────

def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def _load_imitate_config() -> dict:
    """Read label_tool.yaml and return the imitate sub-dict (or {} if absent)."""
    f = _config_file()
    if not f.exists():
        return {}
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse imitate config %s: %s", f, exc)
        return {}
    return raw.get("imitate", {}) or {}


def _load_cforch_config() -> dict:
    """Read cforch section for ollama_url fallback."""
    f = _config_file()
    if not f.exists():
        return {}
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {}
    return raw.get("cforch", {}) or {}


def _ollama_url(cfg: dict) -> str:
    cforch = _load_cforch_config()
    return cfg.get("ollama_url") or cforch.get("ollama_url") or "http://localhost:11434"


def _http_get_json(url: str, timeout: int = 5) -> Any:
    """Fetch JSON from url; raise URLError on failure."""
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_online(base_url: str, health_path: str = "/api/health") -> bool:
    """Return True if the product's health endpoint responds OK."""
    try:
        data = _http_get_json(f"{base_url.rstrip('/')}{health_path}", timeout=2)
        return bool(data)
    except Exception:
        return False


def _extract_sample(
    raw: Any, text_fields: list[str], sample_index: int = 0
) -> dict[str, Any]:
    """Pull one item from a list or dict response and extract text_fields."""
    item: dict[str, Any]
    if isinstance(raw, list):
        if not raw:
            return {}
        item = raw[min(sample_index, len(raw) - 1)]
    elif isinstance(raw, dict):
        # may be {items: [...]} or the item itself
        for key in ("items", "results", "data", "jobs", "listings", "pantry",
                    "saved_searches", "entries", "calls", "records"):
            if key in raw and isinstance(raw[key], list):
                lst = raw[key]
                item = lst[min(sample_index, len(lst) - 1)] if lst else {}
                break
        else:
            item = raw
    else:
        return {}

    parts = []
    for field in text_fields:
        val = item.get(field)
        if val and str(val).strip():
            parts.append(f"**{field}**: {val}")
    return {"item": item, "text": "\n\n".join(parts)}


def _candidates_file() -> Path:
    return _DATA_DIR / "sft_candidates.jsonl"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _run_ollama_streaming(
    ollama_base: str,
    model_id: str,
    prompt: str,
    temperature: float,
) -> tuple[str, int]:
    """Call ollama /api/generate with stream=True; return (full_response, elapsed_ms).

    Blocks until the model finishes; yields nothing — streaming is handled by
    the SSE generator in run_imitate().
    """
    url = f"{ollama_base.rstrip('/')}/api/generate"
    payload = json.dumps({
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }).encode("utf-8")
    req = Request(url, data=payload, method="POST",
                  headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        elapsed = int((time.time() - t0) * 1000)
        return body.get("response", ""), elapsed
    except Exception as exc:
        elapsed = int((time.time() - t0) * 1000)
        raise RuntimeError(str(exc)) from exc


# ── GET /products ──────────────────────────────────────────────────────────────

@router.get("/products")
def get_products() -> dict:
    """List configured CF products with live online status."""
    cfg = _load_imitate_config()
    products_raw = cfg.get("products", []) or []
    products = []
    for p in products_raw:
        if not isinstance(p, dict):
            continue
        base_url = p.get("base_url", "")
        products.append({
            "id":          p.get("id", ""),
            "name":        p.get("name", ""),
            "icon":        p.get("icon", "📦"),
            "description": p.get("description", ""),
            "base_url":    base_url,
            "online":      _is_online(base_url, p.get("health_path", "/api/health")) if base_url else False,
        })
    return {"products": products}


# ── GET /products/{product_id}/sample ─────────────────────────────────────────

@router.get("/products/{product_id}/sample")
def get_sample(product_id: str, index: int = 0) -> dict:
    """Fetch a real sample from the given product's API."""
    cfg = _load_imitate_config()
    products_raw = cfg.get("products", []) or []

    product: dict | None = None
    for p in products_raw:
        if isinstance(p, dict) and p.get("id") == product_id:
            product = p
            break

    if product is None:
        raise HTTPException(404, f"Product '{product_id}' not in config")

    base_url = product.get("base_url", "").rstrip("/")
    endpoint = product.get("sample_endpoint", "")
    if not base_url or not endpoint:
        raise HTTPException(422, "Product missing base_url or sample_endpoint")

    url = f"{base_url}{endpoint}"
    try:
        raw = _http_get_json(url, timeout=5)
    except URLError as exc:
        raise HTTPException(503, f"Product API unreachable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Bad response from product API: {exc}") from exc

    text_fields = product.get("text_fields", []) or []
    extracted = _extract_sample(raw, text_fields, index)
    if not extracted:
        raise HTTPException(404, "No sample items returned by product API")

    prompt_template = product.get("prompt_template", "{text}")
    prompt = prompt_template.replace("{text}", extracted["text"])

    return {
        "product_id":    product_id,
        "sample_index":  index,
        "text":          extracted["text"],
        "prompt":        prompt,
        "raw_item":      extracted.get("item", {}),
    }


# ── GET /run (SSE) ─────────────────────────────────────────────────────────────

@router.get("/run")
def run_imitate(
    prompt: str = "",
    model_ids: str = "",      # comma-separated ollama model IDs
    temperature: float = 0.7,
    product_id: str = "",
) -> StreamingResponse:
    """Run a prompt through selected ollama models and stream results as SSE."""

    if not prompt.strip():
        raise HTTPException(422, "prompt is required")

    ids = [m.strip() for m in model_ids.split(",") if m.strip()]
    if not ids:
        raise HTTPException(422, "model_ids is required")

    cfg = _load_imitate_config()
    ollama_base = _ollama_url(cfg)

    def generate():
        results: list[dict] = []
        yield _sse({"type": "start", "total_models": len(ids)})

        for model_id in ids:
            yield _sse({"type": "model_start", "model": model_id})
            try:
                response, elapsed_ms = _run_ollama_streaming(
                    ollama_base, model_id, prompt, temperature
                )
                result = {
                    "model":      model_id,
                    "response":   response,
                    "elapsed_ms": elapsed_ms,
                    "error":      None,
                }
            except Exception as exc:
                result = {
                    "model":      model_id,
                    "response":   "",
                    "elapsed_ms": 0,
                    "error":      str(exc),
                }
            results.append(result)
            yield _sse({"type": "model_done", **result})

        yield _sse({"type": "complete", "results": results})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── POST /push-corrections ─────────────────────────────────────────────────────

class ImitateResult(BaseModel):
    model: str
    response: str
    elapsed_ms: int
    error: str | None = None


class PushCorrectionsRequest(BaseModel):
    product_id: str
    prompt: str
    results: list[ImitateResult]


@router.post("/push-corrections")
def push_corrections(req: PushCorrectionsRequest) -> dict:
    """Append imitate results to sft_candidates.jsonl for human review."""
    if not req.prompt.strip():
        raise HTTPException(422, "prompt is required")
    if not req.results:
        raise HTTPException(422, "results list is empty")

    ts = datetime.now(timezone.utc).isoformat()
    records = []
    for r in req.results:
        if r.error or not r.response.strip():
            continue
        records.append({
            "id":             str(uuid.uuid4()),
            "source":         "imitate",
            "product_id":     req.product_id,
            "prompt_messages": [{"role": "user", "content": req.prompt}],
            "model_response": r.response,
            "model_id":       r.model,
            "elapsed_ms":     r.elapsed_ms,
            "status":         "pending",
            "created_at":     ts,
        })

    if not records:
        raise HTTPException(422, "No non-error results to push")

    dest = _candidates_file()
    dest.parent.mkdir(parents=True, exist_ok=True)
    for record in records:
        append_jsonl(dest, record)

    return {"pushed": len(records)}
