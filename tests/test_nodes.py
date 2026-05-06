"""Tests for app/nodes.py — /api/nodes-mgmt/* endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import os as _os


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




def _fake_nodes_response(nodes_json: list, services_json: list | None = None):
    """Build side_effect list for two httpx.get calls: nodes then services."""
    mock_nodes = MagicMock()
    mock_nodes.raise_for_status = MagicMock()
    mock_nodes.json.return_value = nodes_json

    mock_services = MagicMock()
    mock_services.raise_for_status = MagicMock()
    mock_services.json.return_value = services_json or []

    return [mock_nodes, mock_services]


def test_list_nodes_coordinator_unreachable_returns_empty(client, tmp_path):
    """Coordinator unreachable — returns [] with no 500."""
    import httpx
    _write_config(tmp_path, {"coordinator_url": "http://fake-coord:7700"})
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        r = client.get("/api/nodes-mgmt/nodes")
    assert r.status_code == 200
    assert r.json() == []


def test_list_nodes_merges_profile_data(client, tmp_path):
    """Profile YAML services_assigned merged with live GPU stats."""
    profiles_dir = tmp_path / "profiles"
    _write_config(tmp_path, {
        "coordinator_url": "http://fake-coord:7700",
        "profiles_dir": str(profiles_dir),
    })
    _write_profile(profiles_dir, "heimdall", {
        "services": {
            "cf-text": {"min_compute_cap": 7.0, "max_mb": 8192, "catalog": {}},
        },
        "nodes": {
            "heimdall": {
                "gpus": [{"id": 0, "vram_mb": 24576, "compute_cap": 8.6,
                           "services": ["cf-text"], "role": "primary", "card": "RTX 3090",
                           "always_on": True}],
                "agent_url": "http://10.1.10.71:7701",
            }
        }
    })

    coord_nodes = [{
        "node_id": "heimdall", "online": True, "agent_url": "http://10.1.10.71:7701",
        "gpus": [{"gpu_id": 0, "card": "RTX 3090", "vram_total_mb": 24576,
                  "vram_used_mb": 4096, "vram_free_mb": 20480,
                  "temp_c": 42.0, "utilization_pct": 15.0, "compute_cap": 8.6}],
    }]

    with patch("httpx.get", side_effect=_fake_nodes_response(coord_nodes)):
        r = client.get("/api/nodes-mgmt/nodes")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    node = data[0]
    assert node["node_id"] == "heimdall"
    assert node["profile_loaded"] is True
    assert node["gpus"][0]["services_assigned"] == ["cf-text"]
    assert node["gpus"][0]["vram_total_mb"] == 24576
    assert "cf-text" in node["services_catalog"]


def test_list_nodes_no_profile_returns_profile_loaded_false(client, tmp_path):
    """Node with no profile YAML — profile_loaded: false, GPU stats still returned."""
    _write_config(tmp_path, {"coordinator_url": "http://fake-coord:7700"})

    coord_nodes = [{
        "node_id": "sif", "online": True, "agent_url": "http://10.1.10.158:7701",
        "gpus": [{"gpu_id": 0, "card": "RTX 5060 Ti", "vram_total_mb": 16384,
                  "vram_used_mb": 0, "vram_free_mb": 16384,
                  "temp_c": None, "utilization_pct": None, "compute_cap": 10.0}],
    }]

    with patch("httpx.get", side_effect=_fake_nodes_response(coord_nodes)):
        r = client.get("/api/nodes-mgmt/nodes")

    assert r.status_code == 200
    data = r.json()
    node = data[0]
    assert node["profile_loaded"] is False
    assert node["gpus"][0]["card"] == "RTX 5060 Ti"
    assert node["services_catalog"] == {}


def test_list_nodes_marks_running_services(client, tmp_path):
    """services_running populated from coordinator /api/services response."""
    profiles_dir = tmp_path / "profiles"
    _write_config(tmp_path, {
        "coordinator_url": "http://fake-coord:7700",
        "profiles_dir": str(profiles_dir),
    })
    _write_profile(profiles_dir, "heimdall", {
        "services": {},
        "nodes": {"heimdall": {"gpus": [{"id": 0, "vram_mb": 24576, "compute_cap": 8.6,
                                          "services": ["cf-text"], "role": "p",
                                          "card": "RTX 3090", "always_on": True}],
                                "agent_url": "http://10.1.10.71:7701"}}
    })

    coord_nodes = [{"node_id": "heimdall", "online": True,
                    "agent_url": "http://10.1.10.71:7701",
                    "gpus": [{"gpu_id": 0, "card": "RTX 3090", "vram_total_mb": 24576,
                              "vram_used_mb": 8192, "vram_free_mb": 16384,
                              "temp_c": 55.0, "utilization_pct": 80.0, "compute_cap": 8.6}]}]
    coord_services = [{"service": "cf-text", "node_id": "heimdall", "gpu_id": 0}]

    with patch("httpx.get", side_effect=_fake_nodes_response(coord_nodes, coord_services)):
        r = client.get("/api/nodes-mgmt/nodes")

    data = r.json()
    assert data[0]["gpus"][0]["services_running"] == ["cf-text"]


# ── GET /api/nodes-mgmt/nodes/{node_id}/profile ────────────────────────────────

def test_get_profile_returns_parsed_yaml(client, tmp_path):
    profiles_dir = tmp_path / "profiles"
    _write_config(tmp_path, {"profiles_dir": str(profiles_dir)})
    profile = {
        "services": {"cf-text": {"min_compute_cap": 7.0, "max_mb": 8192, "catalog": {}}},
        "nodes": {"heimdall": {"gpus": [], "agent_url": "http://10.1.10.71:7701"}},
    }
    _write_profile(profiles_dir, "heimdall", profile)

    r = client.get("/api/nodes-mgmt/nodes/heimdall/profile")
    assert r.status_code == 200
    data = r.json()
    assert "services" in data
    assert "cf-text" in data["services"]


def test_get_profile_404_when_missing(client, tmp_path):
    _write_config(tmp_path, {"profiles_dir": str(tmp_path / "profiles")})
    r = client.get("/api/nodes-mgmt/nodes/nonexistent/profile")
    assert r.status_code == 404


def test_get_profile_500_on_malformed_yaml(client, tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _write_config(tmp_path, {"profiles_dir": str(profiles_dir)})
    (profiles_dir / "bad.yaml").write_text("key: [unclosed", encoding="utf-8")

    r = client.get("/api/nodes-mgmt/nodes/bad/profile")
    assert r.status_code == 500


# ── POST /api/nodes-mgmt/nodes/{node_id}/gpu/{gpu_id}/services ─────────────────


_BASE_PROFILE = {
    "services": {
        "cf-text": {"min_compute_cap": 7.0, "max_mb": 8192, "priority": 1,
                    "catalog": {"llama3": {"vram_mb": 6144, "path": "/m/llama3",
                                           "description": "", "multi_gpu": False, "env": {}}}},
        "ollama":  {"min_compute_cap": 0.0, "max_mb": 2048, "priority": 2, "catalog": {}},
    },
    "nodes": {
        "heimdall": {
            "gpus": [{"id": 0, "vram_mb": 24576, "compute_cap": 8.6,
                       "services": [], "role": "primary", "card": "RTX 3090",
                       "always_on": True}],
            "agent_url": "http://10.1.10.71:7701",
        }
    }
}


def _setup_profile(tmp_path, profile=None):
    profiles_dir = tmp_path / "profiles"
    _write_config(tmp_path, {
        "coordinator_url": "http://fake-coord:7700",
        "profiles_dir": str(profiles_dir),
    })
    _write_profile(profiles_dir, "heimdall", profile or _BASE_PROFILE)
    return profiles_dir


def test_update_services_compatible_writes_and_reloads(client, tmp_path):
    profiles_dir = _setup_profile(tmp_path)

    mock_reload = MagicMock()
    mock_reload.status_code = 200

    with patch("httpx.post", return_value=mock_reload):
        r = client.post(
            "/api/nodes-mgmt/nodes/heimdall/gpu/0/services",
            json={"services": ["cf-text"]},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["reloaded"] is True

    saved = yaml.safe_load((profiles_dir / "heimdall.yaml").read_text())
    assert saved["nodes"]["heimdall"]["gpus"][0]["services"] == ["cf-text"]


def test_update_services_atomic_write_uses_tmp_file(client, tmp_path):
    """YAML must be written to .tmp then renamed — never written directly."""
    profiles_dir = _setup_profile(tmp_path)
    renamed_pairs: list[tuple] = []

    original_replace = _os.replace

    def capture(src, dst):
        renamed_pairs.append((str(src), str(dst)))
        original_replace(src, dst)

    with patch("os.replace", side_effect=capture), \
         patch("httpx.post", return_value=MagicMock(status_code=200)):
        client.post(
            "/api/nodes-mgmt/nodes/heimdall/gpu/0/services",
            json={"services": ["ollama"]},
        )

    assert any(src.endswith(".tmp") for src, dst in renamed_pairs), \
        "Expected atomic write via .tmp rename"


def test_update_services_incompatible_compute_cap_returns_422(client, tmp_path):
    low_cap_profile = {
        **_BASE_PROFILE,
        "nodes": {
            "heimdall": {
                "gpus": [{"id": 0, "vram_mb": 24576, "compute_cap": 6.0,
                           "services": [], "role": "p", "card": "GTX 1080",
                           "always_on": False}],
                "agent_url": "http://10.1.10.71:7701",
            }
        }
    }
    _setup_profile(tmp_path, low_cap_profile)

    r = client.post(
        "/api/nodes-mgmt/nodes/heimdall/gpu/0/services",
        json={"services": ["cf-text"]},
    )
    assert r.status_code == 422
    assert "compute_cap" in r.json()["detail"]


def test_update_services_insufficient_vram_returns_422(client, tmp_path):
    tiny_vram_profile = {
        **_BASE_PROFILE,
        "nodes": {
            "heimdall": {
                "gpus": [{"id": 0, "vram_mb": 512, "compute_cap": 8.6,
                           "services": [], "role": "p", "card": "old",
                           "always_on": False}],
                "agent_url": "http://10.1.10.71:7701",
            }
        }
    }
    _setup_profile(tmp_path, tiny_vram_profile)

    r = client.post(
        "/api/nodes-mgmt/nodes/heimdall/gpu/0/services",
        json={"services": ["cf-text"]},
    )
    assert r.status_code == 422
    assert "VRAM" in r.json()["detail"]


def test_update_services_unknown_service_returns_422(client, tmp_path):
    _setup_profile(tmp_path)
    r = client.post(
        "/api/nodes-mgmt/nodes/heimdall/gpu/0/services",
        json={"services": ["not-a-real-service"]},
    )
    assert r.status_code == 422


def test_update_services_reload_failure_returns_reloaded_false(client, tmp_path):
    """YAML saved but coordinator reload fails — ok: true, reloaded: false."""
    _setup_profile(tmp_path)

    mock_reload = MagicMock()
    mock_reload.status_code = 500

    with patch("httpx.post", return_value=mock_reload):
        r = client.post(
            "/api/nodes-mgmt/nodes/heimdall/gpu/0/services",
            json={"services": ["ollama"]},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["reloaded"] is False
