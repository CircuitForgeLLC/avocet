"""Tests for app/nodes.py — /api/nodes-mgmt/* endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_nodes_globals(tmp_path):
    """Redirect _CONFIG_DIR to tmp_path so tests never read the real config."""
    from app import nodes as nodes_module
    prev = nodes_module._CONFIG_DIR
    nodes_module.set_config_dir(tmp_path)
    yield tmp_path
    nodes_module.set_config_dir(prev)


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def _write_config(config_dir: Path, cforch_cfg: dict) -> None:
    cfg = {"cforch": cforch_cfg}
    (config_dir / "label_tool.yaml").write_text(yaml.dump(cfg), encoding="utf-8")


def _write_profile(profiles_dir: Path, node_id: str, profile: dict) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / f"{node_id}.yaml").write_text(yaml.dump(profile), encoding="utf-8")


def test_nodes_module_imports():
    from app import nodes
    assert hasattr(nodes, "router")
    assert hasattr(nodes, "set_config_dir")


def test_list_nodes_returns_empty_when_no_coordinator(client):
    """No cforch config — endpoint returns empty list, not 500."""
    r = client.get("/api/nodes-mgmt/nodes")
    assert r.status_code == 200
    assert r.json() == []
