"""Tests for app/eval/embed_bench.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_embed_bench_globals(tmp_path):
    """Redirect config dir to tmp_path and reset running flag."""
    from app.eval import embed_bench as mod

    prev_config_dir = mod._CONFIG_DIR
    prev_running = mod._RUN_ACTIVE

    mod.set_config_dir(tmp_path)
    mod._RUN_ACTIVE = False

    yield tmp_path

    mod.set_config_dir(prev_config_dir)
    mod._RUN_ACTIVE = prev_running


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


# ── cosine helper ──────────────────────────────────────────────────────────────

def test_cosine_identical():
    from app.eval.embed_bench import _cosine
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal():
    from app.eval.embed_bench import _cosine
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite():
    from app.eval.embed_bench import _cosine
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_zero_vector_returns_zero():
    from app.eval.embed_bench import _cosine
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


# ── models endpoint ────────────────────────────────────────────────────────────

def test_models_returns_list_with_mock(client, tmp_path):
    """GET /api/embed-bench/models returns list from Ollama tags endpoint."""
    import yaml
    cfg = {"cforch": {"ollama_url": "http://localhost:11434"}}
    (tmp_path / "label_tool.yaml").write_text(yaml.dump(cfg))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "nomic-embed-text", "size": 274302480},
            {"name": "mxbai-embed-large", "size": 669000000},
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/embed-bench/models")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["models"], list)
    assert any(m["name"] == "nomic-embed-text" for m in data["models"])


def test_models_returns_empty_on_ollama_error(client, tmp_path):
    """GET /api/embed-bench/models returns empty list if Ollama unreachable."""
    import httpx
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        r = client.get("/api/embed-bench/models")
    assert r.status_code == 200
    assert r.json()["models"] == []
