"""Avocet — Node Management API.

Proxies cf-orch coordinator and agent APIs to expose per-node GPU state,
service affinity management, and Ollama model management.

Config is read from label_tool.yaml under the `cforch:` key.
The `profiles_dir` key (new) points to the cf-orch node profile YAML directory.

Module-level globals follow the set_config_dir() testability pattern from cforch.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import yaml
from fastapi import APIRouter, HTTPException

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
        coord_nodes: list[dict] = r.json()
    except (httpx.HTTPError, httpx.ConnectError) as exc:
        logger.warning("Coordinator unreachable: %s", exc)
        return []

    try:
        sr = httpx.get(f"{coordinator_url}/api/services", timeout=5.0)
        sr.raise_for_status()
        services_data: list[dict] = sr.json()
    except Exception:
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
