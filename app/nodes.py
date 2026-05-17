"""Avocet — Node Management API.

Proxies cf-orch coordinator and agent APIs to expose per-node GPU state,
service affinity management, and Ollama model management.

Config is read from label_tool.yaml under the `cforch:` key.
The `profiles_dir` key (new) points to the cf-orch node profile YAML directory.

Module-level globals follow the set_config_dir() testability pattern from cforch.py.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_CONFIG_DIR: Path | None = None   # override in tests

router = APIRouter()


# ── Testability seams ──────────────────────────────────────────────────────────

def set_config_dir(path: Path | None) -> None:
    global _CONFIG_DIR
    _CONFIG_DIR = path


# ── Internal helpers ───────────────────────────────────────────────────────────

def _config_file() -> Path:
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR / "label_tool.yaml"
    return _ROOT / "config" / "label_tool.yaml"


def _load_config() -> dict:
    """Read label_tool.yaml cforch section. Returns empty dict on missing or parse error."""
    f = _config_file()
    if not f.exists():
        return {}
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        return raw.get("cforch", {}) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse config %s: %s", f, exc)
        return {}


def _profiles_dir() -> Path | None:
    """Return the cf-orch node profiles directory, or None if not configured."""
    cfg = _load_config()
    pd = cfg.get("profiles_dir", "") or ""
    if pd:
        return Path(pd)
    bench = cfg.get("bench_script", "") or ""
    if bench:
        return Path(bench).parent.parent / "profiles" / "nodes"
    return None


def _profile_path(node_id: str) -> Path | None:
    """Return the path to a node's profile YAML, or None if profiles_dir is unknown."""
    pd = _profiles_dir()
    if pd is None:
        return None
    return pd / f"{node_id}.yaml"


def _load_profile(node_id: str) -> dict | None:
    """Load and parse a node profile YAML. Returns None if not found or malformed."""
    p = _profile_path(node_id)
    if p is None or not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Malformed profile YAML %s: %s", p, exc)
        return None


def _get_ollama_url(node_id: str) -> str:
    """Derive Ollama URL from the node profile's agent_url (same host, port 11434)."""
    profile = _load_profile(node_id)
    if profile:
        nodes_section = profile.get("nodes", {}) or {}
        node_entry = nodes_section.get(node_id, {}) or {}
        agent_url = node_entry.get("agent_url", "") or ""
        if agent_url:
            parsed = urlparse(agent_url)
            return f"{parsed.scheme}://{parsed.hostname}:11434"
    raise HTTPException(
        status_code=404,
        detail=f"Cannot determine Ollama URL for node {node_id}: no agent_url in profile",
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/nodes")
def list_nodes() -> list:
    """Return all nodes with live GPU stats merged with profile YAML."""
    import httpx

    cfg = _load_config()
    coordinator_url = cfg.get("coordinator_url", "") or ""
    if not coordinator_url:
        return []

    try:
        r = httpx.get(f"{coordinator_url}/api/nodes", timeout=5.0)
        r.raise_for_status()
        coord_nodes: list[dict] = r.json().get("nodes", [])
    except httpx.HTTPError as exc:
        logger.warning("Coordinator unreachable: %s", exc)
        return []

    try:
        sr = httpx.get(f"{coordinator_url}/api/services", timeout=5.0)
        sr.raise_for_status()
        services_data: list[dict] = sr.json().get("services", [])
    except httpx.HTTPError:
        logger.warning("Services API unreachable for %s, skipping", coordinator_url)
        services_data = []

    # Build per-node, per-GPU running services map
    running: dict[str, dict[int, list[str]]] = {}
    for svc in services_data:
        nid = svc.get("node_id", "")
        gid = svc.get("gpu_id")
        svc_name = svc.get("service", "")
        if nid and gid is not None and svc_name:
            running.setdefault(nid, {}).setdefault(gid, []).append(svc_name)

    result = []
    for node in coord_nodes:
        node_id = node.get("node_id", "") or node.get("id", "")
        profile = _load_profile(node_id) if node_id else None
        profile_loaded = profile is not None

        gpus = []
        for gpu in (node.get("gpus", []) or []):
            gpu_id = gpu.get("gpu_id", gpu.get("id", 0))
            services_assigned: list[str] = []
            if profile:
                node_entry = (profile.get("nodes", {}) or {}).get(node_id, {}) or {}
                for g in (node_entry.get("gpus", []) or []):
                    if isinstance(g, dict) and g.get("id") == gpu_id:
                        services_assigned = g.get("services", []) or []
                        break
            gpus.append({
                "gpu_id": gpu_id,
                "card": gpu.get("card", ""),
                "vram_total_mb": gpu.get("vram_total_mb", 0),
                "vram_used_mb": gpu.get("vram_used_mb", 0),
                "vram_free_mb": gpu.get("vram_free_mb", 0),
                "temp_c": gpu.get("temp_c"),
                "utilization_pct": gpu.get("utilization_pct"),
                "compute_cap": gpu.get("compute_cap"),
                "services_assigned": services_assigned,
                "services_running": running.get(node_id, {}).get(gpu_id, []),
            })

        services_catalog: dict = {}
        if profile:
            for svc_name, svc_info in (profile.get("services", {}) or {}).items():
                catalog = svc_info.get("catalog", {}) or {}
                services_catalog[svc_name] = {
                    "min_compute_cap": svc_info.get("min_compute_cap", 0.0),
                    "max_mb": svc_info.get("max_mb", 0),
                    "catalog_size": len(catalog),
                }

        result.append({
            "node_id": node_id,
            "online": node.get("online", True),
            "agent_url": node.get("agent_url", ""),
            "gpus": gpus,
            "profile_loaded": profile_loaded,
            "services_catalog": services_catalog,
        })

    return result


@router.get("/nodes/{node_id}/profile")
def get_node_profile(node_id: str) -> dict:
    """Return the full parsed profile YAML for a node."""
    p = _profile_path(node_id)
    if p is None or not p.exists():
        raise HTTPException(404, f"No profile found for node {node_id}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(500, f"Malformed profile YAML: {exc}")
    return data


class UpdateServicesRequest(BaseModel):
    services: list[str]


@router.post("/nodes/{node_id}/gpu/{gpu_id}/services")
def update_gpu_services(node_id: str, gpu_id: int, body: UpdateServicesRequest) -> dict:
    """Set service assignment for a GPU with compatibility validation, then atomic write."""
    import httpx

    cfg = _load_config()
    coordinator_url = cfg.get("coordinator_url", "") or ""

    p = _profile_path(node_id)
    if p is None or not p.exists():
        raise HTTPException(404, f"No profile found for node {node_id}")

    try:
        profile = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(500, f"Malformed profile YAML: {exc}")

    nodes_section = profile.get("nodes", {}) or {}
    node_entry = nodes_section.get(node_id, {}) or {}
    gpu_list = node_entry.get("gpus", []) or []

    gpu_entry = next(
        (g for g in gpu_list if isinstance(g, dict) and g.get("id") == gpu_id),
        None,
    )
    if gpu_entry is None:
        raise HTTPException(404, f"GPU {gpu_id} not found in profile for node {node_id}")

    gpu_compute_cap: float = gpu_entry.get("compute_cap") or 0.0
    gpu_vram_mb: int = gpu_entry.get("vram_mb") or 0
    services_def = profile.get("services", {}) or {}

    for svc_name in body.services:
        if svc_name not in services_def:
            raise HTTPException(422, f"Service '{svc_name}' not defined in profile services dict")
        svc = services_def[svc_name]
        min_cap: float = svc.get("min_compute_cap", 0.0) or 0.0
        if gpu_compute_cap < min_cap:
            raise HTTPException(
                422,
                f"Service '{svc_name}' requires compute_cap >= {min_cap}; GPU has {gpu_compute_cap}",
            )
        catalog = svc.get("catalog", {}) or {}
        min_catalog_vram = (
            min((m.get("vram_mb", 0) for m in catalog.values()), default=0)
            if catalog else svc.get("max_mb", 0)
        )
        if gpu_vram_mb < min_catalog_vram:
            raise HTTPException(
                422,
                f"Service '{svc_name}' requires {min_catalog_vram} MB VRAM; GPU has {gpu_vram_mb} MB",
            )

    # Immutable update of GPU services list
    new_gpu_list = [
        ({**g, "services": body.services} if isinstance(g, dict) and g.get("id") == gpu_id else g)
        for g in gpu_list
    ]
    new_profile = {
        **profile,
        "nodes": {
            **nodes_section,
            node_id: {**node_entry, "gpus": new_gpu_list},
        },
    }

    # Atomic write: write to .tmp then rename
    tmp_yaml = Path(str(p) + ".tmp")
    tmp_yaml.write_text(yaml.dump(new_profile, default_flow_style=False), encoding="utf-8")
    os.replace(tmp_yaml, p)

    # Trigger coordinator profile reload
    reloaded = False
    if coordinator_url:
        try:
            rr = httpx.post(
                f"{coordinator_url}/api/nodes/{node_id}/reload-profile", timeout=5.0
            )
            reloaded = rr.status_code < 300
        except Exception as exc:
            logger.warning("Coordinator reload failed for node %s: %s", node_id, exc)

    return {"ok": True, "reloaded": reloaded, "warnings": []}

# ── Profile save / generate ────────────────────────────────────────────────────

class SaveProfileRequest(BaseModel):
    profile: dict


@router.put("/nodes/{node_id}/profile", status_code=200)
def save_profile(node_id: str, body: SaveProfileRequest) -> dict:
    """Write a full profile dict to disk as YAML, then trigger coordinator reload."""
    p = _profile_path(node_id)
    if p is None:
        raise HTTPException(500, "profiles_dir not configured in label_tool.yaml")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(
        yaml.dump(body.profile, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, p)

    cfg = _load_config()
    coordinator_url = cfg.get("coordinator_url", "") or ""
    reloaded = False
    if coordinator_url:
        try:
            import httpx
            rr = httpx.post(f"{coordinator_url}/api/nodes/{node_id}/reload-profile", timeout=5.0)
            reloaded = rr.status_code < 300
        except Exception as exc:
            logger.warning("Coordinator reload failed for %s: %s", node_id, exc)
    return {"ok": True, "reloaded": reloaded}


@router.post("/nodes/{node_id}/profile/generate")
def generate_profile(node_id: str) -> dict:
    """Return a profile skeleton seeded from coordinator GPU data.

    If a profile already exists, preserves its services section and only
    refreshes the nodes hardware section. Never writes to disk — the caller
    must call PUT /profile to persist.
    """
    import httpx

    cfg = _load_config()
    coordinator_url = cfg.get("coordinator_url", "") or ""
    if not coordinator_url:
        raise HTTPException(503, "coordinator_url not configured")

    try:
        r = httpx.get(f"{coordinator_url}/api/nodes", timeout=5.0)
        r.raise_for_status()
        coord_nodes: list[dict] = r.json().get("nodes", [])
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Coordinator unreachable: {exc}")

    node = next((n for n in coord_nodes if n.get("node_id") == node_id), None)
    if node is None:
        raise HTTPException(404, f"Node {node_id!r} not found in coordinator")

    gpus = [
        {
            "id": g.get("gpu_id", i),
            "vram_mb": g.get("vram_total_mb", 0),
            "compute_cap": g.get("compute_cap", 0.0),
            "card": g.get("card", g.get("name", "")),
            "role": "inference",
            "services": [],
        }
        for i, g in enumerate(node.get("gpus", []))
    ]
    vram_total = max((g["vram_mb"] for g in gpus), default=0)

    existing = _load_profile(node_id) or {}
    return {
        "schema_version": existing.get("schema_version", 1),
        "name": existing.get("name", f"node-{node_id}"),
        "vram_total_mb": vram_total,
        "eviction_timeout_s": existing.get("eviction_timeout_s", 10.0),
        "services": existing.get("services", {}),
        "nodes": {
            node_id: {
                "local_model_root": (
                    (existing.get("nodes", {}) or {})
                    .get(node_id, {})
                    .get("local_model_root", "")
                ),
                "gpus": gpus,
            }
        },
        "model_size_hints": existing.get("model_size_hints", {}),
    }


# ── Ollama model management ────────────────────────────────────────────────────

class PullRequest(BaseModel):
    name: str


@router.get("/nodes/{node_id}/models/ollama")
def list_ollama_models(node_id: str) -> dict:
    """Proxy GET {ollama_url}/api/tags for a specific node."""
    import httpx

    ollama_url = _get_ollama_url(node_id)
    try:
        r = httpx.get(f"{ollama_url}/api/tags", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/nodes/{node_id}/models/ollama/pull")
def pull_ollama_model(node_id: str, body: PullRequest) -> StreamingResponse:
    """Stream Ollama pull progress as SSE events."""
    import httpx

    if not body.name:
        raise HTTPException(400, "name is required")

    ollama_url = _get_ollama_url(node_id)

    def stream():
        try:
            with httpx.stream(
                "POST",
                f"{ollama_url}/api/pull",
                json={"name": body.name, "stream": True},
                timeout=300.0,
            ) as resp:
                for line in resp.iter_lines():
                    if line:
                        yield f"data: {line}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.delete("/nodes/{node_id}/models/ollama/{name:path}")
def delete_ollama_model(node_id: str, name: str) -> dict:
    """Proxy DELETE to Ollama for a specific node."""
    import httpx

    ollama_url = _get_ollama_url(node_id)
    try:
        r = httpx.request("DELETE", f"{ollama_url}/api/delete", json={"name": name}, timeout=10.0)
        if r.status_code == 404:
            raise HTTPException(404, f"Model '{name}' not found on node {node_id}")
        r.raise_for_status()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Ollama unreachable: {exc}")


# ── Model deploy (add catalog entry) ──────────────────────────────────────────

class DeployModelRequest(BaseModel):
    model_id: str
    service_type: str
    vram_mb: int
    description: str = ""
    hf_repo: str = ""
    path: str = ""  # explicit path; if empty, constructed from model_base_path + hf_repo slug


@router.post("/nodes/{node_id}/models/deploy", status_code=200)
def deploy_model(node_id: str, body: DeployModelRequest) -> dict:
    """Register a model in the node's service catalog.

    Adds (or updates) the catalog entry for body.model_id under the given
    service_type in the node's profile YAML, then triggers a coordinator reload.
    Does not download the model — that is the user's responsibility.
    Returns the resolved path so the caller can see where the model should land.
    """
    p = _profile_path(node_id)
    if p is None or not p.exists():
        raise HTTPException(404, f"No profile found for node {node_id!r}")

    try:
        profile = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(500, f"Malformed profile YAML: {exc}")

    services_def = profile.get("services", {}) or {}
    svc = services_def.get(body.service_type)
    if svc is None:
        raise HTTPException(
            422,
            f"Service '{body.service_type}' not defined in node '{node_id}' profile; "
            "add it first via the profile editor",
        )

    # Resolve path: explicit > model_base_path + hf slug > model_id slug
    model_path = body.path.strip()
    if not model_path:
        base = (svc.get("model_base_path", "") or "").rstrip("/")
        if not base:
            raise HTTPException(
                422,
                f"Service '{body.service_type}' has no model_base_path; supply an explicit path",
            )
        slug_src = body.hf_repo.strip() if body.hf_repo.strip() else body.model_id
        hf_slug = slug_src.replace("/", "--")
        model_path = f"{base}/{hf_slug}"

    # Immutable catalog update — spread, never mutate
    entry: dict = {"path": model_path, "vram_mb": body.vram_mb}
    if body.description:
        entry["description"] = body.description
    new_catalog = {**(svc.get("catalog") or {}), body.model_id: entry}
    new_svc = {**svc, "catalog": new_catalog}
    new_services = {**services_def, body.service_type: new_svc}
    new_profile = {**profile, "services": new_services}

    # Atomic write
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(
        yaml.dump(new_profile, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, p)

    # Trigger coordinator reload
    cfg = _load_config()
    coordinator_url = cfg.get("coordinator_url", "") or ""
    reloaded = False
    if coordinator_url:
        try:
            import httpx
            rr = httpx.post(f"{coordinator_url}/api/nodes/{node_id}/reload-profile", timeout=5.0)
            reloaded = rr.status_code < 300
        except Exception as exc:
            logger.warning("Coordinator reload failed for %s: %s", node_id, exc)

    return {"ok": True, "reloaded": reloaded, "path": model_path}
