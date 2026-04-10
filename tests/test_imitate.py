"""Tests for app/imitate.py — product registry, sample extraction, corrections push."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app import imitate as _imitate_module


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_module_globals(tmp_path):
    """Reset module-level config + data dir globals after each test."""
    orig_cfg  = _imitate_module._CONFIG_DIR
    orig_data = _imitate_module._DATA_DIR
    yield
    _imitate_module._CONFIG_DIR = orig_cfg
    _imitate_module._DATA_DIR   = orig_data


@pytest.fixture()
def config_dir(tmp_path) -> Path:
    _imitate_module.set_config_dir(tmp_path)
    return tmp_path


@pytest.fixture()
def data_dir(tmp_path) -> Path:
    _imitate_module.set_data_dir(tmp_path)
    return tmp_path


@pytest.fixture()
def cfg_with_products(config_dir: Path) -> Path:
    """Write a label_tool.yaml with two products."""
    (config_dir / "label_tool.yaml").write_text(
        """
imitate:
  ollama_url: http://localhost:11434
  products:
    - id: peregrine
      name: Peregrine
      icon: "🦅"
      description: Job search assistant
      base_url: http://peregrine.local
      sample_endpoint: /api/jobs
      text_fields: [title, description]
      prompt_template: "Analyze: {text}"
    - id: kiwi
      name: Kiwi
      icon: "🥝"
      description: Pantry tracker
      base_url: http://kiwi.local
      sample_endpoint: /api/inventory
      text_fields: [name, notes]
      prompt_template: "Describe: {text}"
"""
    )
    return config_dir


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ── GET /products ──────────────────────────────────────────────────────────────

def test_products_empty_when_no_config(config_dir, client):
    """Returns empty list when label_tool.yaml has no imitate section."""
    (config_dir / "label_tool.yaml").write_text("accounts: []\n")
    resp = client.get("/api/imitate/products")
    assert resp.status_code == 200
    assert resp.json()["products"] == []


def test_products_listed(cfg_with_products, client):
    """All configured products are returned with expected fields."""
    with patch.object(_imitate_module, "_is_online", return_value=True):
        resp = client.get("/api/imitate/products")
    assert resp.status_code == 200
    products = resp.json()["products"]
    assert len(products) == 2
    ids = {p["id"] for p in products}
    assert ids == {"peregrine", "kiwi"}
    peregrine = next(p for p in products if p["id"] == "peregrine")
    assert peregrine["name"] == "Peregrine"
    assert peregrine["icon"] == "🦅"
    assert peregrine["online"] is True


def test_products_offline_when_unreachable(cfg_with_products, client):
    """Products with unreachable base_url are marked offline."""
    with patch.object(_imitate_module, "_is_online", return_value=False):
        resp = client.get("/api/imitate/products")
    assert all(not p["online"] for p in resp.json()["products"])


# ── GET /products/{id}/sample ─────────────────────────────────────────────────

def test_sample_unknown_product(cfg_with_products, client):
    """Returns 404 for a product id not in config."""
    resp = client.get("/api/imitate/products/nonexistent/sample")
    assert resp.status_code == 404


def test_sample_fetched_from_list(cfg_with_products, client):
    """Extracts first item from a list API response."""
    fake_api = [
        {"title": "Engineer", "description": "Build things"},
        {"title": "Other",    "description": "Ignore me"},
    ]
    with patch.object(_imitate_module, "_http_get_json", return_value=fake_api):
        resp = client.get("/api/imitate/products/peregrine/sample")
    assert resp.status_code == 200
    body = resp.json()
    assert "Engineer" in body["text"]
    assert "Build things" in body["text"]
    assert "Analyze:" in body["prompt"]


def test_sample_fetched_from_dict_with_items_key(cfg_with_products, client):
    """Extracts from a wrapper dict with a recognised list key."""
    fake_api = {"items": [{"title": "Wrapped Job", "description": "In a wrapper"}]}
    with patch.object(_imitate_module, "_http_get_json", return_value=fake_api):
        resp = client.get("/api/imitate/products/peregrine/sample")
    assert resp.status_code == 200
    assert "Wrapped Job" in resp.json()["text"]


def test_sample_503_when_api_unreachable(cfg_with_products, client):
    """Returns 503 when the product API is not reachable."""
    from urllib.error import URLError
    with patch.object(_imitate_module, "_http_get_json", side_effect=URLError("refused")):
        resp = client.get("/api/imitate/products/peregrine/sample")
    assert resp.status_code == 503


def test_sample_404_on_empty_list(cfg_with_products, client):
    """Returns 404 when product API returns an empty list."""
    with patch.object(_imitate_module, "_http_get_json", return_value=[]):
        resp = client.get("/api/imitate/products/peregrine/sample")
    assert resp.status_code == 404


# ── POST /push-corrections ─────────────────────────────────────────────────────

def test_push_corrections_appends_jsonl(cfg_with_products, data_dir, client):
    """Successful push writes records to sft_candidates.jsonl."""
    payload = {
        "product_id": "peregrine",
        "prompt":     "Analyze this job:",
        "results": [
            {"model": "qwen2.5:0.5b", "response": "It's a good job.", "elapsed_ms": 800, "error": None},
            {"model": "llama3.1:8b",  "response": "Strong candidate.", "elapsed_ms": 1500, "error": None},
        ],
    }
    resp = client.post("/api/imitate/push-corrections", json=payload)
    assert resp.status_code == 200
    assert resp.json()["pushed"] == 2

    candidates = (data_dir / "sft_candidates.jsonl").read_text().splitlines()
    assert len(candidates) == 2
    for line in candidates:
        record = json.loads(line)
        assert record["source"] == "imitate"
        assert record["product_id"] == "peregrine"
        assert record["status"] == "pending"
        assert record["prompt_messages"][0]["role"] == "user"


def test_push_corrections_skips_errors(cfg_with_products, data_dir, client):
    """Results with errors are not written to the corrections file."""
    payload = {
        "product_id": "peregrine",
        "prompt":     "Analyze:",
        "results": [
            {"model": "good-model",  "response": "Good answer.", "elapsed_ms": 500, "error": None},
            {"model": "bad-model",   "response": "",             "elapsed_ms": 0,   "error": "connection refused"},
        ],
    }
    resp = client.post("/api/imitate/push-corrections", json=payload)
    assert resp.status_code == 200
    assert resp.json()["pushed"] == 1


def test_push_corrections_empty_prompt_422(cfg_with_products, data_dir, client):
    """Empty prompt returns 422."""
    payload = {
        "product_id": "peregrine",
        "prompt":     "   ",
        "results": [{"model": "m", "response": "r", "elapsed_ms": 1, "error": None}],
    }
    resp = client.post("/api/imitate/push-corrections", json=payload)
    assert resp.status_code == 422


def test_push_corrections_all_errors_422(cfg_with_products, data_dir, client):
    """422 when every result has an error (nothing to push)."""
    payload = {
        "product_id": "peregrine",
        "prompt":     "Analyze:",
        "results": [
            {"model": "m", "response": "", "elapsed_ms": 0, "error": "timed out"},
        ],
    }
    resp = client.post("/api/imitate/push-corrections", json=payload)
    assert resp.status_code == 422


# ── _extract_sample helper ─────────────────────────────────────────────────────

def test_extract_sample_list():
    result = _imitate_module._extract_sample(
        [{"title": "A", "description": "B"}],
        text_fields=["title", "description"],
    )
    assert "A" in result["text"]
    assert "B" in result["text"]


def test_extract_sample_empty_list():
    result = _imitate_module._extract_sample([], text_fields=["title"])
    assert result == {}


def test_extract_sample_respects_index():
    items = [{"title": "First"}, {"title": "Second"}]
    result = _imitate_module._extract_sample(items, ["title"], sample_index=1)
    assert "Second" in result["text"]


def test_extract_sample_clamps_index():
    items = [{"title": "Only"}]
    result = _imitate_module._extract_sample(items, ["title"], sample_index=99)
    assert "Only" in result["text"]
