"""Tests for app/data/log_corpus.py — corpus receiver and labeling endpoints."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.data import log_corpus as lc


VALID_TOKEN = str(uuid.uuid4())
VALID_HOST = "testnode.local"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets its own fresh corpus DB and config dir."""
    monkeypatch.setattr(lc, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(lc, "_DB_PATH", tmp_path / "corpus.db")
    # Config dir pointing to a temp yaml with one test source
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  sources:\n"
        f"    - token: \"{VALID_TOKEN}\"\n"
        f"      source_host: \"{VALID_HOST}\"\n"
        f"      owner: TestOwner\n"
        f"      consent_date: \"2026-05-11\"\n"
        f"      consent_method: signal_chat\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)
    lc._init_db()


@pytest.fixture()
def client():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(lc.router, prefix="/api/corpus")
    return TestClient(app)


def _batch(batch_type="raw_entries", entries=None, source_host=VALID_HOST):
    return {
        "batch_version": 1,
        "batch_id": str(uuid.uuid4()),
        "pushed_at": "2026-05-11T10:00:00Z",
        "source_host": source_host,
        "batch_type": batch_type,
        "watermark_from": 0,
        "watermark_to": 5,
        "entries": entries or [
            {
                "entry_id": str(uuid.uuid4()),
                "source_id": "sonarr",
                "timestamp_iso": "2026-05-11T09:58:00Z",
                "severity": "ERROR",
                "text": "Connection refused to indexer",
                "matched_patterns": [],
            }
        ],
    }


# ── Receive endpoint ───────────────────────────────────────────────────────────

def test_receive_missing_auth(client):
    resp = client.post("/api/corpus/log-batch", json=_batch())
    assert resp.status_code == 401


def test_receive_invalid_token(client):
    resp = client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp.status_code == 403


def test_receive_valid_batch(client):
    resp = client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] is True
    assert data["entries_stored"] == 1


def test_receive_stores_source_host_from_token_not_payload(client):
    """source_host is always taken from the DB lookup, not the payload."""
    payload = _batch(source_host="attacker-injected-host")
    resp = client.post(
        "/api/corpus/log-batch",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    assert resp.status_code == 200
    entries_resp = client.get("/api/corpus/entries")
    entry = entries_resp.json()["entries"][0]
    assert entry["source_host"] == VALID_HOST


def test_receive_skips_empty_text_entries(client):
    payload = _batch(entries=[
        {"entry_id": "e1", "source_id": "svc", "severity": "ERROR", "text": ""},
        {"entry_id": "e2", "source_id": "svc", "severity": "ERROR", "text": "   "},
        {"entry_id": "e3", "source_id": "svc", "severity": "ERROR", "text": "real error"},
    ])
    resp = client.post(
        "/api/corpus/log-batch",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    assert resp.json()["entries_stored"] == 1


def test_receive_incident_bundle(client):
    payload = _batch(batch_type="incident_bundles", entries=[
        {"id": "inc-1", "label": "plex crash", "issue_type": "plex",
         "started_at": "2026-05-11T09:00:00", "ended_at": "2026-05-11T09:30:00",
         "notes": "audio dropped", "created_at": "2026-05-11T09:35:00",
         "severity": "high", "text": "plex crash"},
    ])
    resp = client.post(
        "/api/corpus/log-batch",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["entries_stored"] == 1


# ── Labeling endpoints ─────────────────────────────────────────────────────────

def test_label_entry(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    entry_id = client.get("/api/corpus/entries").json()["entries"][0]["id"]

    resp = client.post(f"/api/corpus/entries/{entry_id}/label", json={
        "failure_type": "software",
        "plain_explanation": "Sonarr lost connection to its indexer — restart the service.",
        "known_pattern": "y",
    })
    assert resp.status_code == 200
    assert resp.json()["labeled"] is True

    entries = client.get("/api/corpus/entries", params={"state": "labeled"}).json()["entries"]
    assert len(entries) == 1
    assert entries[0]["failure_type"] == "software"


def test_label_entry_invalid_failure_type(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    entry_id = client.get("/api/corpus/entries").json()["entries"][0]["id"]
    resp = client.post(f"/api/corpus/entries/{entry_id}/label", json={"failure_type": "aliens"})
    assert resp.status_code == 422


def test_label_entry_missing_failure_type(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    entry_id = client.get("/api/corpus/entries").json()["entries"][0]["id"]
    resp = client.post(f"/api/corpus/entries/{entry_id}/label", json={})
    assert resp.status_code == 422


def test_label_entry_not_found(client):
    resp = client.post("/api/corpus/entries/nonexistent/label", json={"failure_type": "software"})
    assert resp.status_code == 404


def test_skip_entry(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    entry_id = client.get("/api/corpus/entries").json()["entries"][0]["id"]
    resp = client.post(f"/api/corpus/entries/{entry_id}/skip")
    assert resp.status_code == 200

    unlabeled = client.get("/api/corpus/entries").json()["entries"]
    assert len(unlabeled) == 0


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(client):
    stats = client.get("/api/corpus/stats").json()
    assert stats["total_entries"] == 0
    assert stats["batch_count"] == 0


def test_stats_after_receive(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    stats = client.get("/api/corpus/stats").json()
    assert stats["total_entries"] == 1
    assert stats["batch_count"] == 1
    assert stats["by_label_state"].get("unlabeled", 0) == 1


# ── Export ─────────────────────────────────────────────────────────────────────

def test_export_excludes_unlabeled(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    resp = client.get("/api/corpus/export")
    assert resp.status_code == 200
    assert resp.text.strip() == ""


def test_export_includes_labeled(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    entry_id = client.get("/api/corpus/entries").json()["entries"][0]["id"]
    client.post(f"/api/corpus/entries/{entry_id}/label", json={
        "failure_type": "software",
        "plain_explanation": "Sonarr lost connection to indexer.",
    })

    resp = client.get("/api/corpus/export")
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().splitlines() if l]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["output"] == "Sonarr lost connection to indexer."
    assert record["metadata"]["failure_type"] == "software"


def test_export_excludes_pii_flagged(client):
    client.post(
        "/api/corpus/log-batch",
        json=_batch(),
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    entry_id = client.get("/api/corpus/entries").json()["entries"][0]["id"]
    client.post(f"/api/corpus/entries/{entry_id}/label", json={
        "failure_type": "software",
        "plain_explanation": "Contains username — should not export.",
        "pii_flagged": True,
    })

    resp = client.get("/api/corpus/export")
    assert resp.text.strip() == ""
