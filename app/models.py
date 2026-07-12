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
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
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
_MODELS_DIR: Path = Path(
    os.environ.get("AVOCET_MODELS_DIR", str(_ROOT / "models"))
)
_QUEUE_DIR: Path = _ROOT / "data"

# Service-specific model destinations.
# cf-text models land on the NFS-mounted shared asset store so every cluster
# node can reach them without a separate download. Avocet classifiers default
# to a local path but can be redirected via AVOCET_MODELS_DIR — set this to
# /Library/Assets/LLM/avocet/models on NFS-connected nodes to keep all model
# weights out of the repo directory.
# Override via CF_TEXT_MODELS_DIR env var (useful for dev / non-NFS setups).
_CF_TEXT_MODELS_DIR: Path = Path(
    os.environ.get("CF_TEXT_MODELS_DIR", "/Library/Assets/LLM/cf-text/models")
)

# Directory containing per-node YAML profiles for cf-orch.
# Auto-registration writes new catalog entries here on model download.
_CF_ORCH_PROFILES_DIR: Path = Path(
    os.environ.get(
        "CF_ORCH_PROFILES_DIR",
        "/Library/Development/CircuitForge/circuitforge-orch/circuitforge_orch/profiles/nodes",
    )
)

router = APIRouter()

# ── HuggingFace auth ─────────────────────────────────────────────────────────

def _get_hf_token() -> str | None:
    """Return HF token from label_tool.yaml, then HF_TOKEN / HUGGING_FACE_HUB_TOKEN env vars."""
    config_file = _ROOT / "config" / "label_tool.yaml"
    if config_file.exists():
        try:
            import yaml as _yaml
            raw = _yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            token = (raw.get("hf_token") or raw.get("cforch", {}).get("hf_token") or "").strip()
            if token:
                return token
        except Exception:
            pass
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None


# ── GGUF quantization detection ───────────────────────────────────────────────
# Matches quant identifiers in GGUF filenames: Q4_K_M, Q8_0, F16, IQ3_M, etc.
_QUANT_RE = re.compile(
    r'[._-]((?:IQ\d|Q\d)[A-Z0-9_]*|F16|BF16)\.gguf$',
    re.IGNORECASE,
)

# ── Download progress shared state ────────────────────────────────────────────
# Updated by the background download thread; read by GET /download/stream.
_download_progress: dict[str, Any] = {}

# ── HF pipeline_tag → CF service info ────────────────────────────────────────


class _TagInfo(TypedDict):
    adapter: str | None   # Avocet adapter class, or None if handled by another service
    role: str             # Human-readable model role (classifier, stt, tts, vision, …)
    service: str          # CF service that consumes this model type


_TAG_TO_INFO: dict[str, _TagInfo] = {
    # Avocet email classifiers
    "zero-shot-classification":       {"adapter": "ZeroShotAdapter",   "role": "classifier",  "service": "avocet"},
    "text-classification":            {"adapter": "ZeroShotAdapter",   "role": "classifier",  "service": "avocet"},
    "natural-language-inference":     {"adapter": "ZeroShotAdapter",   "role": "classifier",  "service": "avocet"},
    "sentence-similarity":            {"adapter": "RerankerAdapter",   "role": "reranker",    "service": "avocet"},
    "text-ranking":                   {"adapter": "RerankerAdapter",   "role": "reranker",    "service": "avocet"},
    "text-generation":                {"adapter": "GenerationAdapter", "role": "generator",   "service": "cf-text"},
    "text2text-generation":           {"adapter": "GenerationAdapter", "role": "generator",   "service": "cf-text"},
    "summarization":                  {"adapter": "GenerationAdapter", "role": "generator",   "service": "cf-text"},
    # STT — cf-stt speech recognition service
    "automatic-speech-recognition":   {"adapter": None, "role": "stt",       "service": "cf-stt"},
    # Audio language models — audio + text → text (understanding, QA, captioning)
    "audio-text-to-text":             {"adapter": None, "role": "alm",       "service": "cf-stt"},
    # Audio classification — cf-voice sidecar context stream
    "audio-classification":           {"adapter": None, "role": "classifier", "service": "cf-voice"},
    # TTS — cf-tts text-to-speech service
    "text-to-speech":                 {"adapter": None, "role": "tts",       "service": "cf-tts"},
    # Vision classifiers / embedders — cf-vision (SigLIP/CLIP-style models)
    "image-classification":           {"adapter": None, "role": "vision",    "service": "cf-vision"},
    "zero-shot-image-classification": {"adapter": None, "role": "vision",    "service": "cf-vision"},
    "image-feature-extraction":       {"adapter": None, "role": "embedding", "service": "cf-vision"},
    # Generative VLMs (image+text → text) — GGUF quants run via llama.cpp (cf-text).
    # cf-vision is a classifier/embedder service; generative VLMs like Qwen2-VL
    # and LLaVA accept image inputs but are textgen at the backend level.
    # Full-precision HF-format VLMs would use vllm, but our fleet uses GGUF quants.
    "image-text-to-text":             {"adapter": None, "role": "vlm",       "service": "cf-text"},
    "visual-question-answering":      {"adapter": None, "role": "vlm",       "service": "cf-text"},
    # Image generation — cf-image (text → image; distinct from cf-vision image understanding)
    "text-to-image":                  {"adapter": None, "role": "image-gen", "service": "cf-image"},
    # Embedding — cf-core shared embedding layer
    "feature-extraction":             {"adapter": None, "role": "embedding", "service": "cf-core"},
}


# ── Testability seams ──────────────────────────────────────────────────────────

def set_models_dir(path: Path) -> None:
    global _MODELS_DIR
    _MODELS_DIR = path


def set_cf_text_models_dir(path: Path) -> None:
    global _CF_TEXT_MODELS_DIR
    _CF_TEXT_MODELS_DIR = path


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
    """Convert repo_id to a filesystem-safe directory name.

    Uses the HuggingFace Hub convention: owner/model-name → owner--model-name.
    This matches what snapshot_download produces under local_dir and what
    cf-orch uses when constructing model paths for cf-text allocations.
    """
    return repo_id.replace("/", "--")


def _model_dir_for(repo_id: str, service: str | None) -> Path:
    """Return the download destination directory for a model.

    cf-text models → NFS shared asset store (_CF_TEXT_MODELS_DIR) so every
    cluster node can load them without a separate download.
    All other services (avocet classifiers, fine-tunes) → local _MODELS_DIR.
    """
    safe_name = _safe_model_name(repo_id)
    if service == "cf-text":
        return _CF_TEXT_MODELS_DIR / safe_name
    return _MODELS_DIR / safe_name


def _is_installed(repo_id: str, service: str | None = None) -> bool:
    """Check if a model is already downloaded in the appropriate destination."""
    model_dir = _model_dir_for(repo_id, service)
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


# ── cf-orch catalog auto-registration ─────────────────────────────────────────


def _catalog_key(repo_id: str) -> str:
    """Derive a readable catalog key from repo_id.

    ibm-granite/granite-4.1-8b              →  granite-4.1-8b
    facebook/bart-large-cnn                 →  bart-large-cnn
    WithinUsAI/Opus4.7-GODs.Ghost.Codex-4B.GGuF  →  opus4.7-gods.ghost.codex-4b

    The coordinator skips catalog lookup for keys ending in ".gguf" (treats them
    as direct file paths). Strip the suffix so GGUF repo names produce valid keys.
    """
    key = repo_id.split("/", 1)[-1].lower()
    if key.endswith(".gguf"):
        key = key[:-5]
    return key


def _insert_catalog_entry(content: str, entry_lines: str) -> str:
    """Insert entry_lines at the end of the cf-text.catalog section.

    Scans line by line to preserve all comments and original formatting.
    Returns content unchanged if the catalog section cannot be located.
    """
    lines = content.splitlines(keepends=True)

    in_cf_text = False
    in_catalog = False

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        blank_or_comment = not stripped or stripped.startswith("#")

        if not in_cf_text:
            if indent == 2 and stripped.startswith("cf-text:"):
                in_cf_text = True
            continue

        if not in_catalog:
            if indent == 4 and stripped.startswith("catalog:"):
                in_catalog = True
            elif not blank_or_comment and indent <= 2:
                # Left cf-text section without finding a catalog
                return content
            continue

        # Inside catalog: first non-blank/comment line with indent < 6 ends it
        if not blank_or_comment and indent < 6:
            prefix = "\n" if lines[i - 1].strip() else ""
            lines.insert(i, prefix + entry_lines)
            return "".join(lines)

    # Catalog ran to EOF — append there
    if in_catalog:
        prefix = "\n" if lines and lines[-1].strip() else ""
        lines.append(prefix + entry_lines)
        return "".join(lines)

    return content


def _register_in_node_catalogs(
    repo_id: str,
    local_path: Path,
    vram_mb_fp16: int,
    role: str,
) -> list[str]:
    """Insert a cf-text catalog entry into every eligible node YAML.

    A node is eligible when:
    - It has a ``cf-text.catalog`` section
    - The model fits within the node's ``cf-text.max_mb`` at FP16 *or* 4-bit
    - Neither the model key nor the local path is already in the catalog

    Returns the list of node names that were updated.
    """
    try:
        import yaml  # lazy — not in the critical import path
    except ImportError:
        logger.warning("PyYAML not available — skipping catalog registration for %s", repo_id)
        return []

    profiles_dir = _CF_ORCH_PROFILES_DIR
    if not profiles_dir.exists():
        logger.warning(
            "cf-orch profiles dir not found: %s — skipping catalog registration", profiles_dir
        )
        return []

    # Resolve the primary GGUF file — skip mmproj (vision projection matrices).
    # If no .gguf file exists the model is safetensors-only: llama.cpp cannot
    # load it, so catalog registration would produce a broken entry.
    gguf_files = sorted(
        (f for f in local_path.glob("*.gguf") if "mmproj" not in f.name.lower()),
        key=lambda f: f.stat().st_size,
        reverse=True,
    )
    if not gguf_files:
        logger.warning(
            "%s: no .gguf files found in %s — safetensors-only model, "
            "skipping catalog registration",
            repo_id, local_path,
        )
        return []

    # Pick the largest GGUF (highest quality when multiple quant levels downloaded)
    gguf_file = gguf_files[0]
    gguf_filename = gguf_file.name

    model_key = _catalog_key(repo_id)
    local_path_str = str(local_path)
    updated: list[str] = []

    for yaml_file in sorted(profiles_dir.glob("*.yaml")):
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            cf_text = (data.get("services") or {}).get("cf-text")
            if not cf_text:
                continue

            max_mb: int = cf_text.get("max_mb", 0)
            catalog: dict = cf_text.get("catalog") or {}

            # If the node stores models at a different root (model_base_path),
            # remap to that root while keeping the dir name and GGUF filename.
            model_base = cf_text.get("model_base_path", "").rstrip("/")
            if model_base:
                effective_path_str = f"{model_base}/{local_path.name}/{gguf_filename}"
            else:
                effective_path_str = str(gguf_file)

            # Skip if key already exists
            if model_key in catalog:
                logger.debug("Key %r already in %s — skipping", model_key, yaml_file.name)
                continue

            # Skip if this GGUF file or its parent directory is already registered
            registered_paths = {
                str(entry.get("path", ""))
                for entry in catalog.values()
                if isinstance(entry, dict)
            }
            if (
                effective_path_str in registered_paths
                or local_path_str in registered_paths
                or any(p.startswith(local_path_str + "/") for p in registered_paths)
            ):
                logger.debug(
                    "Path %s already registered in %s — skipping",
                    effective_path_str, yaml_file.name,
                )
                continue

            # GGUF models are already quantized; vram_mb_fp16 is the file size.
            # No 4-bit fallback needed — the file is what it is.
            if vram_mb_fp16 > max_mb:
                logger.debug(
                    "%s too large for %s (vram=%d MB, max=%d MB)",
                    repo_id, yaml_file.name, vram_mb_fp16, max_mb,
                )
                continue

            desc = f"{repo_id} ({role}, downloaded via avocet)"
            entry_block = (
                f"      # auto-registered by avocet on download\n"
                f"      {model_key}:\n"
                f"        path: {effective_path_str}\n"
                f"        vram_mb: {vram_mb_fp16}  # {gguf_filename}\n"
                f"        description: \"{desc}\"\n"
            )

            new_content = _insert_catalog_entry(content, entry_block)
            if new_content == content:
                logger.warning("Could not find catalog insertion point in %s", yaml_file.name)
                continue

            yaml_file.write_text(new_content, encoding="utf-8")
            updated.append(yaml_file.stem)
            logger.info(
                "Registered %s in %s (path=%s, vram_mb=%d)",
                model_key, yaml_file.name, effective_path_str, vram_mb_fp16,
            )

        except Exception as exc:
            logger.warning("Could not update %s: %s", yaml_file.name, exc)

    return updated


# ── Background download ────────────────────────────────────────────────────────

def _poll_disk_progress(local_dir: Path, total_bytes: int, stop_event: threading.Event) -> None:
    """Side-thread: poll local_dir size every 2s and update _download_progress.

    snapshot_download is a blocking call with no progress callback, so we watch
    the destination directory grow on disk as a proxy for download progress.
    total_bytes=0 means we don't know the target size; pct stays 0 until done.
    """
    import time
    while not stop_event.is_set():
        try:
            downloaded = sum(
                f.stat().st_size for f in local_dir.rglob("*") if f.is_file()
            )
            _download_progress["downloaded_bytes"] = downloaded
            if total_bytes > 0:
                _download_progress["total_bytes"] = total_bytes
                _download_progress["pct"] = min(downloaded / total_bytes * 100, 99.0)
        except Exception:
            pass
        time.sleep(2)


def _run_download(
    entry_id: str,
    repo_id: str,
    pipeline_tag: str | None,
    adapter_recommendation: str | None,
    role: str | None = None,
    service: str | None = None,
    model_size_bytes: int = 0,
    quant_pattern: str | None = None,
) -> None:
    """Background thread: download model via huggingface_hub.snapshot_download.

    model_size_bytes is the sum of file sizes reported by the HF API (siblings).
    It is used to estimate vram_mb and written to model_info.json so cf-orch can
    budget VRAM when allocating a cf-text instance for this model.

    quant_pattern: when set, restricts snapshot_download to only files matching
    *{quant_pattern}*.gguf (plus metadata). Avoids downloading every quant variant
    from GGUF-only repos like bartowski/*.
    """
    global _download_progress
    local_dir = _model_dir_for(repo_id, service)

    _download_progress = {
        "active": True,
        "repo_id": repo_id,
        "downloaded_bytes": 0,
        "total_bytes": model_size_bytes,
        "pct": 0.0,
        "done": False,
        "error": None,
    }

    stop_poll = threading.Event()
    poll_thread = threading.Thread(
        target=_poll_disk_progress,
        args=(local_dir, model_size_bytes, stop_poll),
        daemon=True,
        name=f"model-poll-{entry_id}",
    )

    try:
        if snapshot_download is None:
            raise RuntimeError("huggingface_hub is not installed")

        local_dir.mkdir(parents=True, exist_ok=True)
        poll_thread.start()

        dl_kwargs: dict[str, Any] = {"repo_id": repo_id, "local_dir": str(local_dir)}
        hf_token = _get_hf_token()
        if hf_token:
            dl_kwargs["token"] = hf_token
        if quant_pattern:
            # Include both cases: repos use mixed conventions (Q6_K vs q6_k).
            dl_kwargs["allow_patterns"] = [
                f"*{quant_pattern.upper()}*.gguf",
                f"*{quant_pattern.lower()}*.gguf",
                "*.json",
                "README.md",
            ]
        snapshot_download(**dl_kwargs)

        # Estimate VRAM from reported file size.
        # HF siblings sizes are pre-quantisation file sizes; add 10% for KV cache
        # and runtime overhead. Falls back to a stat of the local dir if 0.
        if model_size_bytes == 0:
            model_size_bytes = sum(
                f.stat().st_size for f in local_dir.rglob("*") if f.is_file()
            )
        vram_mb = int(model_size_bytes / (1024 * 1024) * 1.1)

        # Write model_info.json alongside downloaded files.
        # local_path + vram_mb are read by cf-orch at allocation time to resolve
        # the full model path and grant the correct VRAM lease.
        model_info = {
            "repo_id": repo_id,
            "pipeline_tag": pipeline_tag,
            "adapter_recommendation": adapter_recommendation,
            "role": role,
            "service": service,
            "model_size_bytes": model_size_bytes,
            "vram_mb": vram_mb,
            "local_path": str(local_dir),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        (local_dir / "model_info.json").write_text(
            json.dumps(model_info, indent=2), encoding="utf-8"
        )

        # Auto-register cf-text models in the cf-orch node YAML catalogs so they
        # appear in the benchmark model list without a manual YAML edit.
        if service == "cf-text":
            registered_on = _register_in_node_catalogs(
                repo_id=repo_id,
                local_path=local_dir,
                vram_mb_fp16=vram_mb,
                role=role or "generator",
            )
            if registered_on:
                logger.info(
                    "Auto-registered %s in node catalogs: %s",
                    repo_id, ", ".join(registered_on),
                )

        _download_progress["done"] = True
        _download_progress["pct"] = 100.0
        _update_queue_entry(entry_id, {"status": "ready", "local_path": str(local_dir)})

    except Exception as exc:
        logger.exception("Download failed for %s: %s", repo_id, exc)
        _download_progress["error"] = str(exc)
        _download_progress["done"] = True
        _update_queue_entry(entry_id, {"status": "failed", "error": str(exc)})
    finally:
        stop_poll.set()
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
    tag_info = _TAG_TO_INFO.get(pipeline_tag) if pipeline_tag else None
    adapter_recommendation = tag_info["adapter"] if tag_info else None
    role = tag_info["role"] if tag_info else None
    service = tag_info["service"] if tag_info else None

    # Determine compatibility and surface a human-readable warning
    _supported = ", ".join(sorted(_TAG_TO_INFO.keys()))
    if tag_info is not None:
        # Any recognized tag is compatible — avocet adapters or another CF service
        compatible = True
        warning: str | None = None
    elif pipeline_tag is None:
        compatible = False
        warning = (
            "This model has no task tag on HuggingFace — adapter type is unknown. "
            "It may not work with Avocet's email classification pipeline."
        )
        logger.warning("No pipeline_tag for %s — no adapter recommendation", repo_id)
    else:
        compatible = False
        warning = (
            f"\"{pipeline_tag}\" models are not yet supported by the CircuitForge model ecosystem. "
            f"Supported task types: {_supported}."
        )
        logger.warning("Unsupported pipeline_tag %r for %s", pipeline_tag, repo_id)

    # Detect GGUF files and parse quant names from siblings list.
    # For GGUF-only repos (bartowski, TheBloke, etc.) this lets the UI show
    # a per-quant size picker instead of downloading every variant.
    siblings = data.get("siblings") or []
    gguf_files: list[dict] = []
    for s in siblings:
        if not isinstance(s, dict):
            continue
        fname: str = s.get("rfilename", "")
        if not fname.lower().endswith(".gguf"):
            continue
        m = _QUANT_RE.search(fname)
        gguf_files.append({
            "filename": fname,
            "size": s.get("size", 0) or 0,
            "quant_name": m.group(1).upper() if m else None,
        })
    gguf_files.sort(key=lambda f: f["size"])

    # model_size_bytes: total of all siblings (for non-GGUF repos) or all GGUFs only.
    # For GGUF repos the frontend will substitute the selected quant's size on submit.
    if gguf_files:
        model_size_bytes: int = sum(f["size"] for f in gguf_files)
    else:
        model_size_bytes = sum(s.get("size", 0) for s in siblings if isinstance(s, dict))

    # Description: first 300 chars of card data (modelId field used as fallback)
    card_data = data.get("cardData") or {}
    description_raw = card_data.get("description") or data.get("modelId") or ""
    description = description_raw[:300] if description_raw else ""

    return {
        "repo_id": repo_id,
        "pipeline_tag": pipeline_tag,
        "adapter_recommendation": adapter_recommendation,
        "role": role,
        "service": service,
        "compatible": compatible,
        "warning": warning,
        "model_size_bytes": model_size_bytes,
        "gguf_files": gguf_files if gguf_files else None,
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
    role: str | None = None
    service: str | None = None
    # Sum of file sizes from HF API siblings list; 0 if unknown.
    # Stored in the queue entry so approve can pass it to _run_download
    # without a second HF API round-trip.
    model_size_bytes: int = 0
    # GGUF quantization pattern (e.g. "Q5_K_M"). When set, snapshot_download
    # restricts to *{quant_pattern}*.gguf instead of fetching all variants.
    quant_pattern: str | None = None


@router.post("/queue", status_code=201)
def add_to_queue(req: QueueAddRequest) -> dict:
    """Add a model to the approval queue with status 'pending'."""
    if _is_installed(req.repo_id, service=req.service):
        raise HTTPException(409, f"{req.repo_id!r} is already installed")
    if _is_queued(req.repo_id):
        raise HTTPException(409, f"{req.repo_id!r} is already in the queue")

    entry = {
        "id": str(uuid4()),
        "repo_id": req.repo_id,
        "pipeline_tag": req.pipeline_tag,
        "adapter_recommendation": req.adapter_recommendation,
        "role": req.role,
        "service": req.service,
        "model_size_bytes": req.model_size_bytes,
        "quant_pattern": req.quant_pattern,
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
        args=(
            entry_id,
            entry["repo_id"],
            entry.get("pipeline_tag"),
            entry.get("adapter_recommendation"),
            entry.get("role"),
            entry.get("service"),
            entry.get("model_size_bytes", 0),
            entry.get("quant_pattern"),
        ),
        daemon=True,
        name=f"model-download-{entry_id}",
    )
    thread.start()

    return {"ok": True}


# ── PATCH /queue/{id} ─────────────────────────────────────────────────────────

class QueuePatchRequest(BaseModel):
    service: str | None = None
    role: str | None = None


@router.patch("/queue/{entry_id}")
def patch_queue_entry(entry_id: str, body: QueuePatchRequest) -> dict:
    """Update mutable fields (service, role) on a pending queue entry."""
    entry = _get_queue_entry(entry_id)
    if entry is None:
        raise HTTPException(404, f"Queue entry {entry_id!r} not found")
    if entry.get("status") != "pending":
        raise HTTPException(409, f"Only pending entries can be patched (current: {entry.get('status')!r})")

    updates: dict = {}
    if body.service is not None:
        updates["service"] = body.service
    if body.role is not None:
        updates["role"] = body.role

    updated = _update_queue_entry(entry_id, updates)
    return updated or {}


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


# ── POST /sync-catalogs ────────────────────────────────────────────────────────

@router.post("/sync-catalogs")
def sync_catalogs() -> dict:
    """Scan all installed cf-text models and register any missing from node YAMLs.

    Reads model_info.json from each directory in the cf-text models dir and calls
    _register_in_node_catalogs() for each. Idempotent — skips models already
    present by key or path.

    Returns a summary of registrations performed.
    """
    if not _CF_TEXT_MODELS_DIR.exists():
        return {"registered": {}, "skipped": [], "message": "cf-text models dir not found"}

    registered: dict[str, list[str]] = {}
    skipped: list[str] = []

    for model_dir in sorted(_CF_TEXT_MODELS_DIR.iterdir()):
        if not model_dir.is_dir():
            continue
        info_file = model_dir / "model_info.json"
        if not info_file.exists():
            skipped.append(model_dir.name)
            continue

        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read model_info.json for %s: %s", model_dir.name, exc)
            skipped.append(model_dir.name)
            continue

        if info.get("service") != "cf-text":
            skipped.append(model_dir.name)
            continue

        repo_id = info.get("repo_id", model_dir.name)
        vram_mb = info.get("vram_mb", 0)
        role = info.get("role", "generator")

        updated_nodes = _register_in_node_catalogs(
            repo_id=repo_id,
            local_path=model_dir,
            vram_mb_fp16=vram_mb,
            role=role,
        )
        if updated_nodes:
            registered[repo_id] = updated_nodes
        else:
            skipped.append(repo_id)

    return {
        "registered": registered,
        "skipped": skipped,
        "message": (
            f"Registered {len(registered)} model(s) on "
            f"{sum(len(v) for v in registered.values())} node(s)"
            if registered
            else "All models already registered (or no eligible nodes found)"
        ),
    }


# ── GET /installed ─────────────────────────────────────────────────────────────

@router.get("/installed")
def list_installed() -> list[dict]:
    """Scan all model directories and return info on each installed model.

    Scans both the local avocet models dir (classifiers, fine-tunes) and the
    shared NFS cf-text models dir, deduplicating by directory path.

    Falls back to queue entry data when model_info.json has null service/role,
    so models downloaded before the pipeline_tag registry existed still group
    correctly in the UI.
    """
    scan_dirs = [_MODELS_DIR]
    if _CF_TEXT_MODELS_DIR != _MODELS_DIR and _CF_TEXT_MODELS_DIR.exists():
        scan_dirs.append(_CF_TEXT_MODELS_DIR)

    # Build a lookup from safe directory name → queue entry for fallback enrichment.
    queue_by_safe_name: dict[str, dict] = {
        _safe_model_name(r["repo_id"]): r
        for r in _read_queue()
        if r.get("repo_id") and r.get("status") not in ("dismissed",)
    }

    results: list[dict] = []
    seen: set[Path] = set()

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for sub in scan_dir.iterdir():
            if not sub.is_dir() or sub in seen:
                continue
            seen.add(sub)

            has_training_info = (sub / "training_info.json").exists()
            has_config = (sub / "config.json").exists()
            has_model_info = (sub / "model_info.json").exists()

            if not (has_training_info or has_config or has_model_info):
                continue

            model_type = "finetuned" if has_training_info else "downloaded"

            # Compute directory size
            size_bytes = sum(f.stat().st_size for f in sub.rglob("*") if f.is_file())

            adapter: str | None = None
            model_id: str | None = None
            role: str | None = None
            service: str | None = None
            vram_mb: int | None = None

            if has_model_info:
                try:
                    info = json.loads((sub / "model_info.json").read_text(encoding="utf-8"))
                    adapter = info.get("adapter_recommendation")
                    model_id = info.get("repo_id")
                    role = info.get("role")
                    service = info.get("service")
                    vram_mb = info.get("vram_mb")
                except Exception:
                    pass
            elif has_training_info:
                try:
                    info = json.loads((sub / "training_info.json").read_text(encoding="utf-8"))
                    adapter = info.get("adapter")
                    model_id = info.get("base_model") or info.get("model_id")
                    role = info.get("role", "classifier")
                    service = info.get("service", "avocet")
                except Exception:
                    pass

            # Fall back to queue entry when model_info.json has null service/role.
            # This covers models downloaded before the pipeline_tag registry existed.
            if (role is None or service is None) and sub.name in queue_by_safe_name:
                q = queue_by_safe_name[sub.name]
                role = role or q.get("role")
                service = service or q.get("service")
                model_id = model_id or q.get("repo_id")

            # Last resort: re-derive from pipeline_tag if we still have no service.
            if service is None and model_id:
                hf_url = f"https://huggingface.co/api/models/{model_id}"
                # Only attempt if we have a pipeline_tag cached somewhere.
                for q in queue_by_safe_name.values():
                    if q.get("repo_id") == model_id and q.get("pipeline_tag"):
                        tag_info = _TAG_TO_INFO.get(q["pipeline_tag"])
                        if tag_info:
                            role = role or tag_info["role"]
                            service = service or tag_info["service"]
                        break

            results.append({
                "name": sub.name,
                "path": str(sub),
                "type": model_type,
                "adapter": adapter,
                "role": role,
                "service": service,
                "size_bytes": size_bytes,
                "vram_mb": vram_mb,
                "model_id": model_id,
            })

    return results


# ── PATCH /installed/{name} ────────────────────────────────────────────────────

class InstalledModelPatch(BaseModel):
    service: str
    role: str


@router.patch("/installed/{name}")
def patch_installed(name: str, body: InstalledModelPatch) -> dict:
    """Manually assign service and role to an installed model.

    Writes the updated values back to model_info.json so they survive restarts,
    and updates any matching queue entry so the UI shows the correct chip.
    """
    if "/" in name or "\\" in name or ".." in name or not name or name.startswith("."):
        raise HTTPException(400, f"Invalid model name {name!r}")

    candidate_dirs = [_MODELS_DIR]
    if _CF_TEXT_MODELS_DIR != _MODELS_DIR:
        candidate_dirs.append(_CF_TEXT_MODELS_DIR)

    model_path: Path | None = None
    for base in candidate_dirs:
        candidate = base / name
        try:
            candidate.resolve().relative_to(base.resolve())
        except ValueError:
            raise HTTPException(400, f"Path traversal detected for name {name!r}")
        if candidate.exists():
            model_path = candidate
            break

    if model_path is None:
        raise HTTPException(404, f"Installed model {name!r} not found")

    info_path = model_path / "model_info.json"
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            info = {}
    else:
        info = {}

    info["service"] = body.service
    info["role"] = body.role
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")

    # Mirror the update into any matching queue entry.
    records = _read_queue()
    updated = False
    for r in records:
        local = r.get("local_path", "")
        matches = (local and Path(local).name == name) or _safe_model_name(r.get("repo_id", "")) == name
        if matches and r.get("status") not in ("dismissed",):
            r["service"] = body.service
            r["role"] = body.role
            updated = True
    if updated:
        _write_queue(records)

    return {"ok": True, "service": body.service, "role": body.role}


# ── DELETE /installed/{name} ───────────────────────────────────────────────────

@router.delete("/installed/{name}")
def delete_installed(name: str) -> dict:
    """Remove an installed model directory by name. Blocks path traversal.

    Searches both the local avocet models dir and the shared cf-text models dir.
    Also dismisses any matching queue entry so the UI doesn't show a stale "ready" card.
    """
    if "/" in name or "\\" in name or ".." in name or not name or name.startswith("."):
        raise HTTPException(400, f"Invalid model name {name!r}: must be a single directory name with no path separators or '..'")

    # Search both model directories
    candidate_dirs = [_MODELS_DIR]
    if _CF_TEXT_MODELS_DIR != _MODELS_DIR:
        candidate_dirs.append(_CF_TEXT_MODELS_DIR)

    model_path: Path | None = None
    for base in candidate_dirs:
        candidate = base / name
        try:
            candidate.resolve().relative_to(base.resolve())
        except ValueError:
            raise HTTPException(400, f"Path traversal detected for name {name!r}")
        if candidate.exists():
            model_path = candidate
            break

    if model_path is None:
        raise HTTPException(404, f"Installed model {name!r} not found in any model directory")

    shutil.rmtree(model_path)

    # Dismiss any queue entries whose local_path matches, or whose repo_id maps to this dir name.
    records = _read_queue()
    updated = False
    for r in records:
        local = r.get("local_path", "")
        matches_path = local and Path(local).name == name
        matches_name = _safe_model_name(r.get("repo_id", "")) == name
        if (matches_path or matches_name) and r.get("status") != "dismissed":
            r["status"] = "dismissed"
            updated = True
    if updated:
        _write_queue(records)

    return {"ok": True}
