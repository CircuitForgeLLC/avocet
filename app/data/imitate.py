"""Avocet — Imitate tab API.

Fetches real samples from sibling CF product APIs, sends them through selected
local LLMs (ollama), and streams responses back to the UI. Results can be
pushed into the SFT corrections queue for human review.

All endpoints registered on `router`. api.py includes this with prefix="/api/imitate".

Module-level globals follow the same testability pattern as cforch.py and sft.py:
override _CONFIG_DIR and _DATA_DIR via set_config_dir() / set_data_dir() in tests.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.utils import append_jsonl

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent
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


def _cforch_url() -> str:
    cforch = _load_cforch_config()
    return cforch.get("coordinator_url") or "http://localhost:7700"


def _resolve_task_model(cforch_base: str, product: str, task: str) -> dict | None:
    """Return {model_id, service_type} for a product.task assignment, or None if not found.

    Calls GET coordinator/api/assignments and filters by product+task.
    The model registry entry is fetched separately to get service_type.
    Returns None (not raises) — callers emit a 'model_done' error event instead.
    """
    try:
        asgn_resp = httpx.get(f"{cforch_base}/api/assignments", timeout=5.0)
        asgn_resp.raise_for_status()
        assignments: list[dict] = asgn_resp.json().get("assignments", []) or []
        match = next(
            (a for a in assignments if a.get("product") == product and a.get("task") == task),
            None,
        )
        if match is None:
            return None
        model_id: str = match.get("model_id", "")
        if not model_id:
            return None

        # Look up service_type from model registry
        reg_resp = httpx.get(f"{cforch_base}/api/model-registry", timeout=5.0)
        service_type = "cf-text"  # sensible default
        if reg_resp.is_success:
            models: list[dict] = reg_resp.json().get("models", []) or []
            reg_entry = next((m for m in models if m.get("model_id") == model_id), None)
            if reg_entry:
                service_type = reg_entry.get("service_type", "cf-text") or "cf-text"

        return {"model_id": model_id, "service_type": service_type}
    except Exception as exc:
        logger.warning("Task resolution failed for %s.%s: %s", product, task, exc)
        return None


def _cforch_catalog(cforch_base: str) -> list[dict]:
    """Fetch the live cf-text catalog from cf-orch.

    Filters out proxy entries (ollama://, vllm://, http://) — those models are
    served by their own services and should not be allocated via cf-text.
    Returns only models with real file-system paths that cf-text can load directly.
    """
    try:
        resp = httpx.get(
            f"{cforch_base}/api/services/cf-text/catalog",
            params={"node_id": "heimdall"},
            timeout=5.0,
        )
        resp.raise_for_status()
        raw = resp.json()
        result = []
        for model_id, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            path = entry.get("path", "")
            # Skip proxy entries — they're routed through other services
            if "://" in path:
                continue
            result.append({
                "id":          model_id,
                "vram_mb":     entry.get("vram_mb", 0),
                "description": entry.get("description", ""),
            })
        return result
    except Exception as exc:
        logger.warning("Could not fetch cf-orch catalog: %s", exc)
        return []


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
    raw: Any,
    text_fields: list[str],
    sample_index: int = 0,
    sample_key: str | None = None,
) -> dict[str, Any]:
    """Pull one item from a list or dict response and extract text_fields.

    sample_key: if provided, unwrap raw[sample_key] before looking for a list.
    Falls back to a set of conventional envelope keys if sample_key is absent.
    """
    item: dict[str, Any]
    if isinstance(raw, list):
        if not raw:
            return {}
        item = raw[min(sample_index, len(raw) - 1)]
    elif isinstance(raw, dict):
        # Use declared sample_key first, then fall back to conventional names.
        _ENVELOPE_KEYS = (
            "samples", "items", "results", "data", "jobs", "listings",
            "pantry", "saved_searches", "entries", "calls", "records",
        )
        search_keys = ([sample_key] if sample_key else []) + list(_ENVELOPE_KEYS)
        for key in search_keys:
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


def _fetch_image_b64(image_url: str) -> str:
    """Download an image URL and return it as a base64 string for ollama.

    Returns empty string on any failure — a missing image is non-fatal;
    the model will still run against the text prompt alone.
    """
    try:
        req = Request(image_url, headers={"User-Agent": "Avocet/1.0"})
        with urlopen(req, timeout=10) as resp:
            return base64.b64encode(resp.read()).decode("ascii")
    except Exception as exc:
        logger.warning("Failed to fetch image %s: %s", image_url, exc)
        return ""


def _run_ollama_streaming(
    ollama_base: str,
    model_id: str,
    prompt: str,
    temperature: float,
    system: str = "",
    images: list[str] | None = None,
) -> tuple[str, int]:
    """Call ollama /api/generate with stream=False; return (full_response, elapsed_ms).

    Blocks until the model finishes; yields nothing — streaming is handled by
    the SSE generator in run_imitate().

    system: optional system prompt passed as a separate field to ollama.
    images: list of base64-encoded image strings (vision models only).
    """
    url = f"{ollama_base.rstrip('/')}/api/generate"
    body: dict = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        body["system"] = system
    if images:
        body["images"] = images
    payload = json.dumps(body).encode("utf-8")
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


def _run_cftext(
    cforch_base: str,
    model_id: str,
    prompt: str,
    system: str,
    temperature: float,
    startup_timeout_s: float = 180.0,
    user_id: str | None = None,
) -> tuple[str, int, bool]:
    """Allocate cf-text via cf-orch, generate, release. Returns (response, elapsed_ms, cold_started).

    Raises RuntimeError on allocation failure or generation error.
    cold_started=True means the service was launched from scratch (caller may log this).

    Cold-start detection uses coordinator state signals (running/stopped) rather than
    polling the service health endpoint — this fails fast on model load errors instead
    of waiting out the full timeout.
    """
    # Allocate
    alloc_resp = httpx.post(
        f"{cforch_base}/api/services/cf-text/allocate",
        json={
            "model_candidates": [model_id],
            "caller": "avocet",
            "pipeline": "imitate",
            **({"user_id": user_id} if user_id else {}),
        },
        timeout=30.0,
    )
    alloc_resp.raise_for_status()
    data = alloc_resp.json()
    service_url: str = data["url"]
    allocation_id: str = data.get("allocation_id", "")
    node_id: str = data.get("node_id", "")
    gpu_id: int | None = data.get("gpu_id")
    cold_started = data.get("started", False) and not data.get("warm", True)

    # Wait for ready using coordinator state signals
    if cold_started:
        deadline = time.monotonic() + startup_timeout_s
        probe_misses = 0
        while time.monotonic() < deadline:
            try:
                status = httpx.get(
                    f"{cforch_base}/api/services/cf-text/status", timeout=5.0
                )
                if status.is_success:
                    instances = status.json().get("instances", [])
                    match = next(
                        (i for i in instances
                         if i.get("node_id") == node_id and i.get("gpu_id") == gpu_id),
                        None,
                    )
                    if match:
                        probe_misses = 0
                        state = match.get("state", "")
                        if state == "running":
                            break
                        elif state == "stopped":
                            if allocation_id:
                                httpx.delete(
                                    f"{cforch_base}/api/services/cf-text/allocations/{allocation_id}",
                                    timeout=5.0,
                                )
                            raise RuntimeError(f"cf-text failed to load {model_id!r} (service stopped)")
                    else:
                        probe_misses += 1
                        if probe_misses >= 6:
                            # Coordinator hasn't registered instance yet — fall back to health poll
                            try:
                                if httpx.get(f"{service_url}/health", timeout=3.0).is_success:
                                    break
                            except Exception:
                                pass
            except RuntimeError:
                raise
            except Exception:
                pass
            time.sleep(2.0)
        else:
            if allocation_id:
                httpx.delete(f"{cforch_base}/api/services/cf-text/allocations/{allocation_id}", timeout=5.0)
            raise RuntimeError(f"cf-text cold start timed out after {startup_timeout_s:.0f}s")

    # Generate
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    t0 = time.time()
    try:
        gen_resp = httpx.post(
            f"{service_url}/v1/chat/completions",
            json={
                "model": model_id,
                "messages": messages,
                "max_tokens": 300,
                "temperature": temperature,
                "stream": False,
            },
            timeout=120.0,
        )
        gen_resp.raise_for_status()
        elapsed_ms = int((time.time() - t0) * 1000)
        content = gen_resp.json()["choices"][0]["message"]["content"]
        return content.strip(), elapsed_ms, cold_started
    except Exception as exc:
        elapsed_ms = int((time.time() - t0) * 1000)
        raise RuntimeError(str(exc)) from exc
    finally:
        if allocation_id:
            try:
                httpx.delete(f"{cforch_base}/api/services/cf-text/allocations/{allocation_id}", timeout=5.0)
            except Exception:
                pass


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
    sample_key = product.get("sample_key") or None
    extracted = _extract_sample(raw, text_fields, index, sample_key=sample_key)
    if not extracted:
        raise HTTPException(404, "No sample items returned by product API")

    prompt_template = product.get("prompt_template", "{text}")
    prompt = prompt_template.replace("{text}", extracted["text"])
    # Also substitute any {field_name} placeholders from the raw item fields.
    item = extracted.get("item", {})
    for field, val in item.items():
        prompt = prompt.replace(f"{{{field}}}", str(val) if val is not None else "")

    # Expose system_prompt and image_url if the product API returns them.
    # system_prompt: Peregrine, Snipe (vision analysis instructions)
    # image_url: Snipe listing photos — Avocet downloads + base64-encodes at run time
    item = extracted.get("item", {})
    system_prompt = str(item.get("system_prompt", "")) if isinstance(item, dict) else ""
    image_url = str(item.get("image_url", "")) if isinstance(item, dict) else ""

    return {
        "product_id":    product_id,
        "sample_index":  index,
        "text":          extracted["text"],
        "prompt":        prompt,
        "system_prompt": system_prompt,
        "image_url":     image_url,
        "raw_item":      item,
    }


# ── GET /catalog ───────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_catalog() -> dict:
    """Return the live cf-text model catalog from cf-orch coordinator."""
    models = _cforch_catalog(_cforch_url())
    return {"models": models}


# ── GET /run (SSE) ─────────────────────────────────────────────────────────────

def _get_imitate_session(request: Any, response: Any) -> "CloudUser | None":
    """Optional session dependency — returns None when cloud_session is unavailable."""
    try:
        from app.cloud_session import get_session
        return get_session(request, response)
    except Exception:
        return None


@router.get("/run")
def run_imitate(
    prompt: str = "",
    model_ids: str = "",          # comma-separated ollama model IDs
    cf_text_model_ids: str = "",  # comma-separated cf-text model IDs (via cf-orch)
    task_ids: str = "",           # comma-separated "product/task" strings — resolved via assignments
    temperature: float = 0.7,
    product_id: str = "",
    system: str = "",             # optional system prompt
    image_url: str = "",          # optional image URL for vision models
    session: "Any" = Depends(_get_imitate_session),
) -> StreamingResponse:
    """Run a prompt through selected models and stream results as SSE.

    Models can be selected three ways (combinable):
    - model_ids: explicit ollama model IDs
    - cf_text_model_ids: explicit cf-text model IDs routed via cf-orch
    - task_ids: "product/task" strings resolved via the coordinator assignments table

    If image_url is provided, the image is downloaded once and passed to every
    model as a base64-encoded blob — allowing vision-capable local models to
    evaluate listing photos the same way Snipe's background task pipeline does.
    """

    if not prompt.strip():
        raise HTTPException(422, "prompt is required")

    ollama_ids  = [m.strip() for m in model_ids.split(",")         if m.strip()]
    cftext_ids  = [m.strip() for m in cf_text_model_ids.split(",") if m.strip()]
    raw_task_ids = [t.strip() for t in task_ids.split(",")         if t.strip()]

    # Resolve task assignments to concrete model IDs, routing to the right service.
    # Models that fail to resolve emit an error event at run time (non-fatal).
    if raw_task_ids:
        cforch_base = _cforch_url()
        for task_spec in raw_task_ids:
            parts = task_spec.split("/", 1)
            if len(parts) != 2:
                logger.warning("Skipping malformed task_id %r (expected product/task)", task_spec)
                continue
            product_name, task_name = parts
            resolved = _resolve_task_model(cforch_base, product_name, task_name)
            if resolved is None:
                logger.warning("No assignment found for task %r", task_spec)
                # Emit error at stream time via a sentinel in cftext_ids with a special label.
                # We instead store the failed task_spec to emit a model_done error.
                cftext_ids.append(f"__task_unresolved__:{task_spec}")
                continue
            mid = resolved["model_id"]
            svc = resolved["service_type"]
            if svc == "ollama":
                if mid not in ollama_ids:
                    ollama_ids.append(mid)
            else:
                # cf-text, vllm, and any other cf-orch-managed service
                if mid not in cftext_ids:
                    cftext_ids.append(mid)

    if not ollama_ids and not cftext_ids:
        raise HTTPException(422, "model_ids, cf_text_model_ids, or task_ids is required")

    cfg = _load_imitate_config()
    ollama_base = _ollama_url(cfg)
    cforch_base = _cforch_url()
    system_ctx = system.strip() or ""
    total_models = len(ollama_ids) + len(cftext_ids)

    # Download image once before streaming — shared across ollama vision models
    images: list[str] = []
    if image_url.strip():
        b64 = _fetch_image_b64(image_url.strip())
        if b64:
            images = [b64]

    def generate():
        results: list[dict] = []
        yield _sse({"type": "start", "total_models": total_models, "has_image": bool(images)})

        # Ollama models
        for model_id in ollama_ids:
            yield _sse({"type": "model_start", "model": model_id, "service": "ollama"})
            try:
                response, elapsed_ms = _run_ollama_streaming(
                    ollama_base, model_id, prompt, temperature,
                    system=system_ctx, images=images or None,
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

        # cf-text models via cf-orch — fan out in parallel when multiple models selected
        # Partition the list: real cf-text IDs vs unresolved-task sentinels.
        cftext_real = [m for m in cftext_ids if not m.startswith("__task_unresolved__:")]
        cftext_unresolved = [m for m in cftext_ids if m.startswith("__task_unresolved__:")]
        for sentinel in cftext_unresolved:
            task_spec = sentinel.split(":", 1)[1]
            result = {
                "model": task_spec,
                "response": "",
                "elapsed_ms": 0,
                "error": f"No assignment configured for task '{task_spec}'",
            }
            results.append(result)
            yield _sse({"type": "model_done", **result})

        if cftext_real:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # Announce all models upfront so the UI can show loading states immediately
            for model_id in cftext_real:
                yield _sse({"type": "model_start", "model": model_id, "service": "cf-text"})

            _user_id: str | None = getattr(session, "user_id", None)
            # Only forward real cloud user IDs — skip local/anon sessions
            if _user_id in (None, "local", "local-dev") or (_user_id or "").startswith("anon-"):
                _user_id = None

            with ThreadPoolExecutor(max_workers=len(cftext_real)) as pool:
                future_to_model = {
                    pool.submit(
                        _run_cftext, cforch_base, mid, prompt, system_ctx, temperature,
                        180.0, _user_id,
                    ): mid
                    for mid in cftext_real
                }
                for future in as_completed(future_to_model):
                    model_id = future_to_model[future]
                    try:
                        response, elapsed_ms, cold_started = future.result()
                        if cold_started:
                            yield _sse({"type": "model_coldstart", "model": model_id})
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
