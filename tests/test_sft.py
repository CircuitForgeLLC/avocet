"""API integration tests for app/sft.py — /api/sft/* endpoints."""
import json
import pytest
from fastapi.testclient import TestClient
from pathlib import Path


@pytest.fixture(autouse=True)
def reset_sft_globals(tmp_path):
    from app import sft as sft_module
    _prev_data = sft_module._SFT_DATA_DIR
    _prev_cfg = sft_module._SFT_CONFIG_DIR
    sft_module.set_sft_data_dir(tmp_path)
    sft_module.set_sft_config_dir(tmp_path)
    yield
    sft_module.set_sft_data_dir(_prev_data)
    sft_module.set_sft_config_dir(_prev_cfg)


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def _make_record(id: str, run_id: str = "2026-04-07-143022") -> dict:
    return {
        "id": id, "source": "cf-orch-benchmark",
        "benchmark_run_id": run_id, "timestamp": "2026-04-07T10:00:00Z",
        "status": "needs_review",
        "prompt_messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Write a Python function that adds two numbers."},
        ],
        "model_response": "def add(a, b): return a - b",
        "corrected_response": None,
        "quality_score": 0.2, "failure_reason": "pattern_match: 0/2 matched",
        "task_id": "code-fn", "task_type": "code",
        "task_name": "Code: Write a Python function",
        "model_id": "Qwen/Qwen2.5-3B", "model_name": "Qwen2.5-3B",
        "node_id": "heimdall", "gpu_id": 0, "tokens_per_sec": 38.4,
    }


def _write_run(tmp_path, run_id: str, records: list[dict]) -> Path:
    run_dir = tmp_path / "bench_results" / run_id
    run_dir.mkdir(parents=True)
    sft_path = run_dir / "sft_candidates.jsonl"
    sft_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    return sft_path


def _write_config(tmp_path, bench_results_dir: Path) -> None:
    import yaml
    cfg = {"sft": {"bench_results_dir": str(bench_results_dir)}}
    (tmp_path / "label_tool.yaml").write_text(
        yaml.dump(cfg, allow_unicode=True), encoding="utf-8"
    )


# ── /api/sft/runs ──────────────────────────────────────────────────────────

def test_runs_returns_empty_when_no_config(client):
    r = client.get("/api/sft/runs")
    assert r.status_code == 200
    assert r.json() == []


def test_runs_returns_available_runs(client, tmp_path):
    _write_run(tmp_path, "2026-04-07-143022", [_make_record("a"), _make_record("b")])
    _write_config(tmp_path, tmp_path / "bench_results")
    r = client.get("/api/sft/runs")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "2026-04-07-143022"
    assert data[0]["candidate_count"] == 2
    assert data[0]["already_imported"] is False


def test_runs_marks_already_imported(client, tmp_path):
    _write_run(tmp_path, "2026-04-07-143022", [_make_record("a")])
    _write_config(tmp_path, tmp_path / "bench_results")
    from app import sft as sft_module
    candidates = sft_module._candidates_file()
    candidates.parent.mkdir(parents=True, exist_ok=True)
    candidates.write_text(
        json.dumps(_make_record("a", run_id="2026-04-07-143022")) + "\n",
        encoding="utf-8"
    )
    r = client.get("/api/sft/runs")
    assert r.json()[0]["already_imported"] is True


# ── /api/sft/import ─────────────────────────────────────────────────────────

def test_import_adds_records(client, tmp_path):
    _write_run(tmp_path, "2026-04-07-143022", [_make_record("a"), _make_record("b")])
    _write_config(tmp_path, tmp_path / "bench_results")
    r = client.post("/api/sft/import", json={"run_id": "2026-04-07-143022"})
    assert r.status_code == 200
    assert r.json() == {"imported": 2, "skipped": 0}


def test_import_is_idempotent(client, tmp_path):
    _write_run(tmp_path, "2026-04-07-143022", [_make_record("a")])
    _write_config(tmp_path, tmp_path / "bench_results")
    client.post("/api/sft/import", json={"run_id": "2026-04-07-143022"})
    r = client.post("/api/sft/import", json={"run_id": "2026-04-07-143022"})
    assert r.json() == {"imported": 0, "skipped": 1}


def test_import_unknown_run_returns_404(client, tmp_path):
    _write_config(tmp_path, tmp_path / "bench_results")
    r = client.post("/api/sft/import", json={"run_id": "nonexistent"})
    assert r.status_code == 404
