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


# ── Pipeline ingest endpoint ───────────────────────────────────────────────────

def _make_pipeline_file(directory: Path, name: str, lines: list[dict]) -> Path:
    """Write a JSONL pipeline log file to directory."""
    p = directory / name
    p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    return p


_PIPELINE_LINE = {
    "ts": "2026-05-17T10:00:00Z",
    "level": "INFO",
    "logger": "scripts.pipeline.purple_carrot_scraper",
    "msg": "Fetched recipe page",
    "extra": {"url": "https://example.com/recipe/1", "status": 200},
}


def test_pipeline_ingest_returns_404_when_dir_not_configured(client, tmp_path):
    """No pipeline_ingest_dir in config — endpoint returns 404."""
    resp = client.post("/api/corpus/pipeline-ingest")
    assert resp.status_code == 404


def test_pipeline_ingest_empty_dir(client, tmp_path, monkeypatch):
    """Configured dir exists but is empty — returns zeros, no error."""
    ingest_dir = tmp_path / "pipeline_logs"
    ingest_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  pipeline_ingest_dir: \"{ingest_dir}\"\n  sources: []\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)

    resp = client.post("/api/corpus/pipeline-ingest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ingested_files"] == 0
    assert data["skipped_files"] == 0
    assert data["entries_stored"] == 0


def test_pipeline_ingest_ingests_valid_file(client, tmp_path, monkeypatch):
    """Valid JSONL file is ingested; entries appear in corpus."""
    ingest_dir = tmp_path / "pipeline_logs"
    ingest_dir.mkdir()
    _make_pipeline_file(ingest_dir, "scraper_20260517.jsonl", [
        _PIPELINE_LINE,
        {**_PIPELINE_LINE, "msg": "Saved 3 recipes", "level": "INFO"},
    ])

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  pipeline_ingest_dir: \"{ingest_dir}\"\n  sources: []\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)

    resp = client.post("/api/corpus/pipeline-ingest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ingested_files"] == 1
    assert data["entries_stored"] == 2

    entries = client.get("/api/corpus/entries", params={"limit": 10}).json()["entries"]
    assert len(entries) == 2
    assert all(e["source_host"] == "pipeline_scrape" for e in entries)


def test_pipeline_ingest_source_id_from_logger(client, tmp_path, monkeypatch):
    """source_id is populated from the 'logger' field of each log line."""
    ingest_dir = tmp_path / "pipeline_logs"
    ingest_dir.mkdir()
    _make_pipeline_file(ingest_dir, "run_20260517.jsonl", [_PIPELINE_LINE])

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  pipeline_ingest_dir: \"{ingest_dir}\"\n  sources: []\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)

    client.post("/api/corpus/pipeline-ingest")
    entries = client.get("/api/corpus/entries", params={"limit": 10}).json()["entries"]
    assert entries[0]["source_id"] == "scripts.pipeline.purple_carrot_scraper"


def test_pipeline_ingest_idempotent(client, tmp_path, monkeypatch):
    """Calling the endpoint twice does not re-ingest already-processed files."""
    ingest_dir = tmp_path / "pipeline_logs"
    ingest_dir.mkdir()
    _make_pipeline_file(ingest_dir, "scraper_20260517.jsonl", [_PIPELINE_LINE])

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  pipeline_ingest_dir: \"{ingest_dir}\"\n  sources: []\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)

    client.post("/api/corpus/pipeline-ingest")
    resp2 = client.post("/api/corpus/pipeline-ingest")

    data = resp2.json()
    assert data["ingested_files"] == 0
    assert data["skipped_files"] == 1
    assert data["entries_stored"] == 0

    entries = client.get("/api/corpus/entries", params={"limit": 10}).json()["entries"]
    assert len(entries) == 1  # still just the one from the first ingest


def test_pipeline_ingest_skips_non_jsonl(client, tmp_path, monkeypatch):
    """Non-.jsonl files in the dir are silently ignored."""
    ingest_dir = tmp_path / "pipeline_logs"
    ingest_dir.mkdir()
    (ingest_dir / "notes.txt").write_text("this is not a log file")
    (ingest_dir / "run.csv").write_text("a,b,c\n1,2,3")
    _make_pipeline_file(ingest_dir, "valid_20260517.jsonl", [_PIPELINE_LINE])

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  pipeline_ingest_dir: \"{ingest_dir}\"\n  sources: []\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)

    resp = client.post("/api/corpus/pipeline-ingest")
    assert resp.json()["ingested_files"] == 1


def test_pipeline_ingest_skips_malformed_lines(client, tmp_path, monkeypatch):
    """Lines that are not valid JSON are skipped; valid lines in the same file still land."""
    ingest_dir = tmp_path / "pipeline_logs"
    ingest_dir.mkdir()
    p = ingest_dir / "mixed_20260517.jsonl"
    p.write_text(
        json.dumps(_PIPELINE_LINE) + "\n"
        "this is not json\n"
        + json.dumps({**_PIPELINE_LINE, "msg": "another valid line"}),
        encoding="utf-8",
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  pipeline_ingest_dir: \"{ingest_dir}\"\n  sources: []\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)

    resp = client.post("/api/corpus/pipeline-ingest")
    assert resp.status_code == 200
    assert resp.json()["entries_stored"] == 2  # 2 valid lines, 1 skipped


def test_pipeline_ingest_new_file_after_first_run(client, tmp_path, monkeypatch):
    """A new file added after the first ingest is picked up on the next call."""
    ingest_dir = tmp_path / "pipeline_logs"
    ingest_dir.mkdir()
    _make_pipeline_file(ingest_dir, "run_a.jsonl", [_PIPELINE_LINE])

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "label_tool.yaml").write_text(
        f"corpus:\n  pipeline_ingest_dir: \"{ingest_dir}\"\n  sources: []\n"
    )
    monkeypatch.setattr(lc, "_CONFIG_DIR", config_dir)

    client.post("/api/corpus/pipeline-ingest")  # ingest run_a.jsonl

    _make_pipeline_file(ingest_dir, "run_b.jsonl", [
        {**_PIPELINE_LINE, "msg": "Second run line"},
    ])

    resp2 = client.post("/api/corpus/pipeline-ingest")
    data = resp2.json()
    assert data["ingested_files"] == 1
    assert data["skipped_files"] == 1
    assert data["entries_stored"] == 1
