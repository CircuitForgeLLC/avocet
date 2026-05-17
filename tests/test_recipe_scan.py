"""Tests for app/data/recipe_scan.py — recipe scan labeling endpoints."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.data import recipe_scan as rs


EXTRACTED = {"title": "Shepherd's Pie", "ingredients": ["lamb", "potato"], "steps": ["brown meat", "mash potato"]}
GROUND_TRUTH = {"title": "Shepherd's Pie", "ingredients": ["ground lamb", "mashed potato", "peas"], "steps": ["brown meat", "add veg", "mash potato", "bake"]}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_DB_PATH", tmp_path / "recipe_scan.db")
    rs._init_db()


@pytest.fixture()
def client():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(rs.router, prefix="/api/recipe-scan")
    return TestClient(app)


def _item(**kwargs) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "image_path": "/Library/Assets/kiwi/scans/pc_test.jpg",
        "modality": kwargs.get("modality", "scanner"),
        "source": kwargs.get("source", "purple_carrot"),
        "extracted": kwargs.get("extracted", EXTRACTED),
        "ground_truth": kwargs.get("ground_truth", GROUND_TRUTH),
    }


def _import(client, items: list[dict]) -> None:
    resp = client.post("/api/recipe-scan/import", json={"items": items})
    assert resp.status_code == 200


# ── Import ─────────────────────────────────────────────────────────────────────

def test_import_stores_items(client):
    _import(client, [_item()])
    stats = client.get("/api/recipe-scan/stats").json()
    assert stats["total"] == 1
    assert stats["by_status"]["pending"] == 1


def test_import_rejects_unknown_modality(client):
    bad = _item()
    bad["modality"] = "telepathy"
    resp = client.post("/api/recipe-scan/import", json={"items": [bad]})
    assert resp.status_code == 422


def test_import_is_idempotent(client):
    item = _item()
    _import(client, [item])
    _import(client, [item])  # same id — should not duplicate
    stats = client.get("/api/recipe-scan/stats").json()
    assert stats["total"] == 1


def test_import_multiple_items(client):
    _import(client, [_item(), _item(), _item()])
    assert client.get("/api/recipe-scan/stats").json()["total"] == 3


# ── Next ───────────────────────────────────────────────────────────────────────

def test_next_returns_404_when_queue_empty(client):
    resp = client.get("/api/recipe-scan/next")
    assert resp.status_code == 404


def test_next_returns_pending_item(client):
    item = _item()
    _import(client, [item])
    resp = client.get("/api/recipe-scan/next")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == item["id"]
    assert data["status"] == "pending"
    assert "extracted" in data
    assert "ground_truth" in data


def test_next_skips_non_pending(client):
    item = _item()
    _import(client, [item])
    client.post(f"/api/recipe-scan/items/{item['id']}/reject")
    resp = client.get("/api/recipe-scan/next")
    assert resp.status_code == 404


# ── Approve ────────────────────────────────────────────────────────────────────

def test_approve_marks_item_approved(client):
    item = _item()
    _import(client, [item])
    resp = client.post(f"/api/recipe-scan/items/{item['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    stats = client.get("/api/recipe-scan/stats").json()
    assert stats["by_status"]["approved"] == 1


def test_approve_returns_404_for_unknown_id(client):
    resp = client.post("/api/recipe-scan/items/no-such-id/approve")
    assert resp.status_code == 404


# ── Edit ───────────────────────────────────────────────────────────────────────

def test_edit_stores_corrected_json(client):
    item = _item()
    _import(client, [item])
    corrected = {**GROUND_TRUTH, "servings": 4}
    resp = client.post(
        f"/api/recipe-scan/items/{item['id']}/edit",
        json={"corrected": corrected},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "edited"
    stats = client.get("/api/recipe-scan/stats").json()
    assert stats["by_status"]["edited"] == 1


def test_edit_requires_corrected_field(client):
    item = _item()
    _import(client, [item])
    resp = client.post(f"/api/recipe-scan/items/{item['id']}/edit", json={})
    assert resp.status_code == 422


# ── Reject ─────────────────────────────────────────────────────────────────────

def test_reject_marks_item_rejected(client):
    item = _item()
    _import(client, [item])
    resp = client.post(
        f"/api/recipe-scan/items/{item['id']}/reject",
        json={"reason": "OCR completely unreadable"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_reject_without_reason_is_valid(client):
    item = _item()
    _import(client, [item])
    resp = client.post(f"/api/recipe-scan/items/{item['id']}/reject")
    assert resp.status_code == 200


# ── Export ─────────────────────────────────────────────────────────────────────

def test_export_empty_when_nothing_approved(client):
    item = _item()
    _import(client, [item])
    resp = client.get("/api/recipe-scan/export")
    assert resp.status_code == 200
    assert resp.text.strip() == ""


def test_export_includes_approved_item(client):
    item = _item()
    _import(client, [item])
    client.post(f"/api/recipe-scan/items/{item['id']}/approve")
    resp = client.get("/api/recipe-scan/export")
    lines = [l for l in resp.text.strip().splitlines() if l]
    assert len(lines) == 1
    pair = json.loads(lines[0])
    assert pair["id"] == item["id"]
    assert pair["modality"] == "scanner"
    assert "messages" in pair
    assert len(pair["messages"]) == 2
    assert pair["messages"][0]["role"] == "user"
    assert pair["messages"][1]["role"] == "assistant"


def test_export_includes_edited_item_with_correction(client):
    item = _item()
    _import(client, [item])
    corrected = {**GROUND_TRUTH, "servings": 4}
    client.post(
        f"/api/recipe-scan/items/{item['id']}/edit",
        json={"corrected": corrected},
    )
    resp = client.get("/api/recipe-scan/export")
    lines = [l for l in resp.text.strip().splitlines() if l]
    pair = json.loads(lines[0])
    assistant_content = json.loads(pair["messages"][1]["content"])
    assert assistant_content["servings"] == 4


def test_export_excludes_rejected_items(client):
    item = _item()
    _import(client, [item])
    client.post(f"/api/recipe-scan/items/{item['id']}/reject")
    resp = client.get("/api/recipe-scan/export")
    assert resp.text.strip() == ""


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_counts_all_statuses(client):
    items = [_item(), _item(), _item(), _item()]
    _import(client, items)
    client.post(f"/api/recipe-scan/items/{items[0]['id']}/approve")
    client.post(f"/api/recipe-scan/items/{items[1]['id']}/edit", json={"corrected": GROUND_TRUTH})
    client.post(f"/api/recipe-scan/items/{items[2]['id']}/reject")
    stats = client.get("/api/recipe-scan/stats").json()
    assert stats["total"] == 4
    assert stats["by_status"]["pending"] == 1
    assert stats["by_status"]["approved"] == 1
    assert stats["by_status"]["edited"] == 1
    assert stats["by_status"]["rejected"] == 1
    assert stats["export_ready"] == 2  # approved + edited
