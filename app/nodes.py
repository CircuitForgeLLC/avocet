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
from fastapi.responses import StreamingResponse

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
        detail=f"Cannot determine Ollama URL for node {node_id} — no agent_url in profile",
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/nodes")
def list_nodes() -> list:
    """List all nodes visible to the cf-orch coordinator.

    Returns an empty list if no coordinator_url is configured.
    Full implementation arrives in Task 2 (live coordinator proxy).
    """
    cfg = _load_config()
    if not cfg.get("coordinator_url"):
        return []
    return []  # full implementation in Task 2
