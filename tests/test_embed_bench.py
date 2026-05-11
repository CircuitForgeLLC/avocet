"""Tests for app/eval/embed_bench.py."""
from __future__ import annotations

import json
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

    with patch("app.eval.embed_bench.httpx.get", return_value=mock_resp):
        r = client.get("/api/embed-bench/models")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["models"], list)
    assert any(m["name"] == "nomic-embed-text" for m in data["models"])


def test_models_returns_empty_on_ollama_error(client, tmp_path):
    """GET /api/embed-bench/models returns empty list if Ollama unreachable."""
    import httpx
    with patch("app.eval.embed_bench.httpx.get", side_effect=httpx.ConnectError("refused")):
        r = client.get("/api/embed-bench/models")
    assert r.status_code == 200
    assert r.json()["models"] == []


# ── run endpoint ───────────────────────────────────────────────────────────────

def test_run_empty_corpus_returns_422(client):
    r = client.post("/api/embed-bench/run", json={
        "corpus": [], "queries": ["test"], "models": ["nomic-embed-text"], "top_k": 3
    })
    assert r.status_code == 422


def test_run_empty_queries_returns_422(client):
    r = client.post("/api/embed-bench/run", json={
        "corpus": ["chunk 1"], "queries": [], "models": ["nomic-embed-text"], "top_k": 3
    })
    assert r.status_code == 422


def test_run_empty_models_returns_422(client):
    r = client.post("/api/embed-bench/run", json={
        "corpus": ["chunk 1"], "queries": ["test"], "models": [], "top_k": 3
    })
    assert r.status_code == 422


def _fake_embed_response(texts: list[str]) -> MagicMock:
    """Build a mock httpx.post response returning unit vectors for each text."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": [{"embedding": [1.0, 0.0, 0.0] if i % 2 == 0 else [0.0, 1.0, 0.0]}
                 for i, _ in enumerate(texts)]
    }
    return resp


def _collect_sse(raw: bytes) -> list[dict]:
    """Parse SSE stream bytes into a list of decoded event dicts."""
    events = []
    for line in raw.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_run_single_model_returns_result_and_done(client, tmp_path):
    import yaml
    (tmp_path / "label_tool.yaml").write_text(yaml.dump({"cforch": {"ollama_url": "http://localhost:11434"}}))

    with patch("app.eval.embed_bench.httpx.post", return_value=_fake_embed_response(["chunk 1", "chunk 2"])):
        r = client.post("/api/embed-bench/run", json={
            "corpus": ["chunk 1", "chunk 2"],
            "queries": ["what is chunk one?"],
            "models": ["nomic-embed-text"],
            "top_k": 2,
        })

    assert r.status_code == 200
    events = _collect_sse(r.content)
    types = [e["type"] for e in events]
    assert "result" in types
    assert types[-1] == "done"
    result_events = [e for e in events if e["type"] == "result"]
    assert result_events[0]["model"] == "nomic-embed-text"
    assert result_events[0]["query_idx"] == 0
    assert len(result_events[0]["hits"]) <= 2


def test_run_two_models_returns_two_result_events_per_query(client, tmp_path):
    import yaml
    (tmp_path / "label_tool.yaml").write_text(yaml.dump({"cforch": {"ollama_url": "http://localhost:11434"}}))

    with patch("app.eval.embed_bench.httpx.post", return_value=_fake_embed_response(["chunk A", "chunk B"])):
        r = client.post("/api/embed-bench/run", json={
            "corpus": ["chunk A", "chunk B"],
            "queries": ["find it"],
            "models": ["nomic-embed-text", "mxbai-embed-large"],
            "top_k": 2,
        })

    events = _collect_sse(r.content)
    result_events = [e for e in events if e["type"] == "result"]
    models_seen = {e["model"] for e in result_events}
    assert "nomic-embed-text" in models_seen
    assert "mxbai-embed-large" in models_seen


# ── rate + export ──────────────────────────────────────────────────────────────

def test_rate_appends_jsonl_line(client, tmp_path):
    r = client.post("/api/embed-bench/rate", json={
        "query": "test query",
        "model": "nomic-embed-text",
        "chunk_text": "some text",
        "chunk_idx": 2,
        "rating": "relevant",
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    ratings_file = tmp_path / "embed_bench_ratings.jsonl"
    assert ratings_file.exists()
    line = json.loads(ratings_file.read_text().strip())
    assert line["query"] == "test query"
    assert line["rating"] == "relevant"
    assert line["chunk_idx"] == 2
    assert "timestamp" in line


def test_export_csv_two_rows(client, tmp_path):
    for i in range(2):
        client.post("/api/embed-bench/rate", json={
            "query": f"q{i}", "model": "nomic-embed-text",
            "chunk_text": f"chunk {i}", "chunk_idx": i, "rating": "relevant",
        })
    r = client.get("/api/embed-bench/export?format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.strip().splitlines()
    assert len(lines) == 3          # header + 2 rows
    assert "query" in lines[0]


def test_export_json_two_entries(client, tmp_path):
    for i in range(2):
        client.post("/api/embed-bench/rate", json={
            "query": f"q{i}", "model": "nomic-embed-text",
            "chunk_text": f"chunk {i}", "chunk_idx": i, "rating": "not_relevant",
        })
    r = client.get("/api/embed-bench/export?format=json")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["rating"] == "not_relevant"


def test_export_empty_returns_csv_header_only(client):
    r = client.get("/api/embed-bench/export?format=csv")
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) == 1          # header only
    assert "query" in lines[0]
