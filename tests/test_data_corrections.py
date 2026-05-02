"""Tests for app/data/corrections.py -- POST /api/sft/ingest.

The corrections router is mounted at prefix="/api/sft" via the app/sft.py
backward-compat shim, so ingest lives at /api/sft/ingest.
"""
import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_globals(tmp_path):
    from app.data import corrections as corr_module
    corr_module.set_data_dir(tmp_path)
    corr_module.set_config_dir(tmp_path)
    yield


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


_VALID_PAYLOAD = {
    "source": "peregrine",
    "task_type": "email_classification",
    "prompt": "Classify this email: ...",
    "response": "skip",
    "correction": "action_required",
    "label": "action_required",
}

_SECRET = "test-secret-abc123"


def test_ingest_503_when_secret_not_configured(client, monkeypatch):
    monkeypatch.delenv("AVOCET_INGESTION_SECRET", raising=False)
    r = client.post("/api/sft/ingest", json=_VALID_PAYLOAD,
                    headers={"Authorization": f"Bearer {_SECRET}"})
    assert r.status_code == 503


def test_ingest_401_when_no_auth_header(client, monkeypatch):
    monkeypatch.setenv("AVOCET_INGESTION_SECRET", _SECRET)
    r = client.post("/api/sft/ingest", json=_VALID_PAYLOAD)
    assert r.status_code == 401


def test_ingest_401_when_malformed_header(client, monkeypatch):
    monkeypatch.setenv("AVOCET_INGESTION_SECRET", _SECRET)
    r = client.post("/api/sft/ingest", json=_VALID_PAYLOAD,
                    headers={"Authorization": "Token bad-format"})
    assert r.status_code == 401


def test_ingest_403_when_wrong_secret(client, monkeypatch):
    monkeypatch.setenv("AVOCET_INGESTION_SECRET", _SECRET)
    r = client.post("/api/sft/ingest", json=_VALID_PAYLOAD,
                    headers={"Authorization": "Bearer wrong-secret"})
    assert r.status_code == 403


def test_ingest_creates_approved_record(client, monkeypatch, tmp_path):
    from app.data import corrections as corr_module
    monkeypatch.setenv("AVOCET_INGESTION_SECRET", _SECRET)
    corr_module.set_data_dir(tmp_path)
    r = client.post("/api/sft/ingest", json=_VALID_PAYLOAD,
                    headers={"Authorization": f"Bearer {_SECRET}"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "id" in data
    candidates = corr_module.read_jsonl(corr_module._candidates_file())
    assert len(candidates) == 1
    rec = candidates[0]
    assert rec["status"] == "approved"
    assert rec["source"] == "peregrine"
    assert rec["corrected_response"] == "action_required"
    assert rec["id"] == data["id"]


def test_ingest_also_writes_to_approved_file(client, monkeypatch, tmp_path):
    from app.data import corrections as corr_module
    monkeypatch.setenv("AVOCET_INGESTION_SECRET", _SECRET)
    corr_module.set_data_dir(tmp_path)
    r = client.post("/api/sft/ingest", json=_VALID_PAYLOAD,
                    headers={"Authorization": f"Bearer {_SECRET}"})
    assert r.status_code == 200
    approved = corr_module.read_jsonl(corr_module._approved_file())
    assert len(approved) == 1
    assert approved[0]["id"] == r.json()["id"]


def test_ingest_without_label_is_accepted(client, monkeypatch, tmp_path):
    from app.data import corrections as corr_module
    monkeypatch.setenv("AVOCET_INGESTION_SECRET", _SECRET)
    corr_module.set_data_dir(tmp_path)
    payload = {**_VALID_PAYLOAD, "label": None}
    r = client.post("/api/sft/ingest", json=payload,
                    headers={"Authorization": f"Bearer {_SECRET}"})
    assert r.status_code == 200
