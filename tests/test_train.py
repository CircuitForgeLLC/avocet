"""Tests for app/train/train.py -- /api/train/* endpoints."""
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_globals(tmp_path):
    from app.train import train as train_module
    train_module.set_db_path(tmp_path / "train_jobs.db")
    train_module.set_models_dir(tmp_path / "models")
    train_module._running_procs.clear()
    yield
    train_module._running_procs.clear()


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def _parse_sse(content: bytes) -> list[dict]:
    events = []
    for line in content.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_list_jobs_empty(client):
    r = client.get("/api/train/jobs")
    assert r.status_code == 200
    assert r.json() == {"jobs": []}


def test_create_job_returns_queued_record(client):
    r = client.post("/api/train/jobs",
                    json={"type": "classifier", "model_key": "deberta-small",
                          "config_json": {"epochs": 3}})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "queued"
    assert data["type"] == "classifier"
    assert data["model_key"] == "deberta-small"
    assert "id" in data


def test_create_job_invalid_type_returns_400(client):
    r = client.post("/api/train/jobs",
                    json={"type": "unknown-type", "model_key": "deberta-small"})
    assert r.status_code == 400


def test_create_job_appears_in_list(client):
    client.post("/api/train/jobs", json={"type": "classifier", "model_key": "deberta-small"})
    r = client.get("/api/train/jobs")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) == 1


def test_get_job_returns_record(client):
    r = client.post("/api/train/jobs", json={"type": "classifier", "model_key": "deberta-small"})
    job_id = r.json()["id"]
    r2 = client.get(f"/api/train/jobs/{job_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == job_id


def test_get_job_404_for_unknown(client):
    r = client.get("/api/train/jobs/no-such-id")
    assert r.status_code == 404


def test_cancel_queued_job(client):
    r = client.post("/api/train/jobs", json={"type": "classifier", "model_key": "deberta-small"})
    job_id = r.json()["id"]
    r2 = client.delete(f"/api/train/jobs/{job_id}/cancel")
    assert r2.status_code == 200
    assert r2.json()["status"] == "cancelled"
    r3 = client.get(f"/api/train/jobs/{job_id}")
    assert r3.json()["status"] == "cancelled"


def test_cancel_completed_job_returns_409(client):
    from app.train import train as train_module
    train_module._init_db()
    with train_module._db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, type, model_key, status, config_json, created_at) "
            "VALUES ('abc', 'classifier', 'deberta-small', 'completed', '{}', '2026-05-01T00:00:00Z')"
        )
    r = client.delete("/api/train/jobs/abc/cancel")
    assert r.status_code == 409


def test_cancel_terminates_running_proc(client):
    from app.train import train as train_module
    mock_proc = MagicMock()
    mock_proc.wait = MagicMock()
    r = client.post("/api/train/jobs", json={"type": "classifier", "model_key": "deberta-small"})
    job_id = r.json()["id"]
    train_module._running_procs[job_id] = mock_proc
    with train_module._db() as conn:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
    r2 = client.delete(f"/api/train/jobs/{job_id}/cancel")
    assert r2.status_code == 200
    mock_proc.terminate.assert_called_once()


def test_run_job_streams_sse(client):
    r = client.post("/api/train/jobs", json={"type": "classifier", "model_key": "deberta-small"})
    job_id = r.json()["id"]
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["Epoch 1\n", "Done\n"])
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock()
    with patch("app.train.train._subprocess.Popen", return_value=mock_proc):
        r2 = client.get(f"/api/train/jobs/{job_id}/run")
    assert r2.status_code == 200
    assert "text/event-stream" in r2.headers.get("content-type", "")
    events = _parse_sse(r2.content)
    assert any(e["type"] == "complete" for e in events)


def test_run_job_marks_completed_in_db(client):
    from app.train import train as train_module
    r = client.post("/api/train/jobs", json={"type": "classifier", "model_key": "deberta-small"})
    job_id = r.json()["id"]
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock()
    with patch("app.train.train._subprocess.Popen", return_value=mock_proc):
        client.get(f"/api/train/jobs/{job_id}/run")
    r2 = client.get(f"/api/train/jobs/{job_id}")
    assert r2.json()["status"] == "completed"


def test_run_job_marks_failed_on_nonzero_exit(client):
    r = client.post("/api/train/jobs", json={"type": "classifier", "model_key": "deberta-small"})
    job_id = r.json()["id"]
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 1
    mock_proc.wait = MagicMock()
    with patch("app.train.train._subprocess.Popen", return_value=mock_proc):
        client.get(f"/api/train/jobs/{job_id}/run")
    r2 = client.get(f"/api/train/jobs/{job_id}")
    assert r2.json()["status"] == "failed"


def test_run_nonqueued_job_returns_409(client):
    from app.train import train as train_module
    train_module._init_db()
    with train_module._db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, type, model_key, status, config_json, created_at) "
            "VALUES ('xyz', 'classifier', 'deberta-small', 'running', '{}', '2026-05-01T00:00:00Z')"
        )
    r = client.get("/api/train/jobs/xyz/run")
    assert r.status_code == 409


def test_run_unknown_job_returns_404(client):
    r = client.get("/api/train/jobs/no-such/run")
    assert r.status_code == 404


def test_results_empty_when_no_models_dir(client):
    r = client.get("/api/train/results")
    assert r.status_code == 200
    assert r.json() == {"results": []}


def test_results_returns_training_info(client, tmp_path):
    from app.train import train as train_module
    models_dir = tmp_path / "models" / "avocet-deberta-small"
    models_dir.mkdir(parents=True)
    train_module.set_models_dir(tmp_path / "models")
    info = {"name": "avocet-deberta-small", "val_macro_f1": 0.712, "sample_count": 401}
    (models_dir / "training_info.json").write_text(json.dumps(info))
    r = client.get("/api/train/results")
    assert r.status_code == 200
    data = r.json()
    assert any(d["name"] == "avocet-deberta-small" for d in data["results"])
