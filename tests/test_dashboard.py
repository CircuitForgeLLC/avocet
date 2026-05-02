"""Tests for app/dashboard.py -- GET /api/dashboard."""
import json
import pytest
import yaml
from fastapi.testclient import TestClient
from pathlib import Path


@pytest.fixture(autouse=True)
def reset_globals(tmp_path):
    from app import dashboard as dash_module
    dash_module.set_data_dir(tmp_path)
    dash_module.set_config_dir(tmp_path)
    yield


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def _write_score(tmp_path: Path, records: list[dict]) -> None:
    (tmp_path / "email_score.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )

def _write_summary(tmp_path: Path, run_id: str, ts: str, score: float) -> None:
    run_dir = tmp_path / "bench_results" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"timestamp": ts, "best_macro_f1": score})
    )


def test_dashboard_returns_expected_keys(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    data = r.json()
    for key in ("labeled_since_last_eval", "last_eval_timestamp", "last_eval_best_score",
                "active_jobs", "corrections_pending", "corrections_export_ready", "signals"):
        assert key in data, f"missing key: {key}"
    for sig in ("data_to_eval", "eval_to_train", "train_to_fleet"):
        assert sig in data["signals"], f"missing signal: {sig}"


def test_dashboard_empty_state(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["labeled_since_last_eval"] == 0
    assert data["last_eval_timestamp"] is None
    assert data["last_eval_best_score"] is None
    assert data["active_jobs"] == []
    assert data["corrections_pending"] == 0
    assert data["corrections_export_ready"] == 0


def test_labeled_since_counts_all_when_no_eval(client, tmp_path):
    _write_score(tmp_path, [
        {"id": "a", "label": "neutral", "labeled_at": "2026-05-01T10:00:00+00:00"},
        {"id": "b", "label": "neutral", "labeled_at": "2026-05-01T11:00:00+00:00"},
    ])
    r = client.get("/api/dashboard")
    assert r.json()["labeled_since_last_eval"] == 2


def test_labeled_since_filters_by_eval_timestamp(client, tmp_path):
    _write_summary(tmp_path, "2026-05-01-100000", "2026-05-01T10:00:00+00:00", 0.80)
    _write_score(tmp_path, [
        {"id": "a", "label": "neutral", "labeled_at": "2026-05-01T09:00:00+00:00"},
        {"id": "b", "label": "neutral", "labeled_at": "2026-05-01T11:00:00+00:00"},
    ])
    (tmp_path / "label_tool.yaml").write_text(
        yaml.dump({"cforch": {"results_dir": str(tmp_path / "bench_results")}})
    )
    r = client.get("/api/dashboard")
    data = r.json()
    assert data["labeled_since_last_eval"] == 1
    assert abs(data["last_eval_best_score"] - 0.80) < 0.001


def test_data_to_eval_false_below_threshold(client, tmp_path):
    _write_score(tmp_path, [{"id": str(i), "label": "neutral",
                              "labeled_at": "2026-05-01T10:00:00+00:00"} for i in range(10)])
    (tmp_path / "label_tool.yaml").write_text(yaml.dump({"pipeline": {"data_eval_threshold": 50}}))
    r = client.get("/api/dashboard")
    assert r.json()["signals"]["data_to_eval"] is False


def test_data_to_eval_true_at_threshold(client, tmp_path):
    _write_score(tmp_path, [{"id": str(i), "label": "neutral",
                              "labeled_at": "2026-05-01T10:00:00+00:00"} for i in range(50)])
    (tmp_path / "label_tool.yaml").write_text(yaml.dump({"pipeline": {"data_eval_threshold": 50}}))
    r = client.get("/api/dashboard")
    assert r.json()["signals"]["data_to_eval"] is True


def test_corrections_pending_count(client, tmp_path):
    candidates = [
        {"id": "c1", "status": "needs_review"},
        {"id": "c2", "status": "needs_review"},
        {"id": "c3", "status": "discarded"},
    ]
    (tmp_path / "sft_candidates.jsonl").write_text(
        "\n".join(json.dumps(c) for c in candidates) + "\n"
    )
    r = client.get("/api/dashboard")
    assert r.json()["corrections_pending"] == 2


def test_corrections_export_ready_count(client, tmp_path):
    approved = [
        {"id": "a1", "status": "approved", "corrected_response": "Good answer"},
        {"id": "a2", "status": "approved", "corrected_response": ""},
        {"id": "a3", "status": "approved", "corrected_response": "Another answer"},
    ]
    (tmp_path / "sft_approved.jsonl").write_text(
        "\n".join(json.dumps(a) for a in approved) + "\n"
    )
    r = client.get("/api/dashboard")
    assert r.json()["corrections_export_ready"] == 2
