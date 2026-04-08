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


# ── /api/sft/queue ──────────────────────────────────────────────────────────

def _populate_candidates(tmp_path, records: list[dict]) -> None:
    from app import sft as sft_module
    path = sft_module._candidates_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def test_queue_returns_needs_review_only(client, tmp_path):
    records = [
        _make_record("a"),                                         # needs_review
        {**_make_record("b"), "status": "approved"},              # should not appear
        {**_make_record("c"), "status": "discarded"},             # should not appear
    ]
    _populate_candidates(tmp_path, records)
    r = client.get("/api/sft/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == "a"


def test_queue_pagination(client, tmp_path):
    records = [_make_record(str(i)) for i in range(25)]
    _populate_candidates(tmp_path, records)
    r = client.get("/api/sft/queue?page=1&per_page=10")
    data = r.json()
    assert data["total"] == 25
    assert len(data["items"]) == 10
    r2 = client.get("/api/sft/queue?page=3&per_page=10")
    assert len(r2.json()["items"]) == 5


def test_queue_empty_when_no_file(client):
    r = client.get("/api/sft/queue")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "per_page": 20}


# ── /api/sft/submit ─────────────────────────────────────────────────────────

def test_submit_correct_sets_approved(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    r = client.post("/api/sft/submit", json={
        "id": "a", "action": "correct",
        "corrected_response": "def add(a, b): return a + b",
    })
    assert r.status_code == 200
    from app import sft as sft_module
    records = sft_module._read_candidates()
    assert records[0]["status"] == "approved"
    assert records[0]["corrected_response"] == "def add(a, b): return a + b"


def test_submit_correct_also_appends_to_approved_file(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    client.post("/api/sft/submit", json={
        "id": "a", "action": "correct",
        "corrected_response": "def add(a, b): return a + b",
    })
    from app import sft as sft_module
    from app.utils import read_jsonl
    approved = read_jsonl(sft_module._approved_file())
    assert len(approved) == 1
    assert approved[0]["id"] == "a"


def test_submit_discard_sets_discarded(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    r = client.post("/api/sft/submit", json={"id": "a", "action": "discard"})
    assert r.status_code == 200
    from app import sft as sft_module
    assert sft_module._read_candidates()[0]["status"] == "discarded"


def test_submit_flag_sets_model_rejected(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    r = client.post("/api/sft/submit", json={"id": "a", "action": "flag"})
    assert r.status_code == 200
    from app import sft as sft_module
    assert sft_module._read_candidates()[0]["status"] == "model_rejected"


def test_submit_correct_empty_response_returns_422(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    r = client.post("/api/sft/submit", json={
        "id": "a", "action": "correct", "corrected_response": "   ",
    })
    assert r.status_code == 422


def test_submit_correct_null_response_returns_422(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    r = client.post("/api/sft/submit", json={
        "id": "a", "action": "correct", "corrected_response": None,
    })
    assert r.status_code == 422


def test_submit_unknown_id_returns_404(client, tmp_path):
    r = client.post("/api/sft/submit", json={"id": "nope", "action": "discard"})
    assert r.status_code == 404


def test_submit_already_approved_returns_409(client, tmp_path):
    _populate_candidates(tmp_path, [{**_make_record("a"), "status": "approved"}])
    r = client.post("/api/sft/submit", json={"id": "a", "action": "discard"})
    assert r.status_code == 409


# ── /api/sft/undo ────────────────────────────────────────────────────────────

def test_undo_restores_discarded_to_needs_review(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    client.post("/api/sft/submit", json={"id": "a", "action": "discard"})
    r = client.post("/api/sft/undo", json={"id": "a"})
    assert r.status_code == 200
    from app import sft as sft_module
    assert sft_module._read_candidates()[0]["status"] == "needs_review"


def test_undo_removes_approved_from_approved_file(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    client.post("/api/sft/submit", json={
        "id": "a", "action": "correct",
        "corrected_response": "def add(a, b): return a + b",
    })
    client.post("/api/sft/undo", json={"id": "a"})
    from app import sft as sft_module
    from app.utils import read_jsonl
    approved = read_jsonl(sft_module._approved_file())
    assert not any(r["id"] == "a" for r in approved)


def test_undo_already_needs_review_returns_409(client, tmp_path):
    _populate_candidates(tmp_path, [_make_record("a")])
    r = client.post("/api/sft/undo", json={"id": "a"})
    assert r.status_code == 409


# ── /api/sft/export ──────────────────────────────────────────────────────────

def test_export_returns_approved_as_sft_jsonl(client, tmp_path):
    from app import sft as sft_module
    from app.utils import write_jsonl
    approved = {
        **_make_record("a"),
        "status": "approved",
        "corrected_response": "def add(a, b): return a + b",
        "prompt_messages": [
            {"role": "system", "content": "You are a coding assistant."},
            {"role": "user", "content": "Write a Python add function."},
        ],
    }
    write_jsonl(sft_module._approved_file(), [approved])
    _populate_candidates(tmp_path, [approved])

    r = client.get("/api/sft/export")
    assert r.status_code == 200
    assert "application/x-ndjson" in r.headers["content-type"]
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["messages"][-1] == {
        "role": "assistant", "content": "def add(a, b): return a + b"
    }
    assert record["messages"][0]["role"] == "system"
    assert record["messages"][1]["role"] == "user"


def test_export_excludes_non_approved(client, tmp_path):
    from app import sft as sft_module
    from app.utils import write_jsonl
    records = [
        {**_make_record("a"), "status": "discarded", "corrected_response": None},
        {**_make_record("b"), "status": "needs_review", "corrected_response": None},
    ]
    write_jsonl(sft_module._approved_file(), records)
    r = client.get("/api/sft/export")
    assert r.text.strip() == ""


def test_export_empty_when_no_approved_file(client):
    r = client.get("/api/sft/export")
    assert r.status_code == 200
    assert r.text.strip() == ""


# ── /api/sft/stats ───────────────────────────────────────────────────────────

def test_stats_counts_by_status(client, tmp_path):
    from app import sft as sft_module
    from app.utils import write_jsonl
    records = [
        _make_record("a"),
        {**_make_record("b"), "status": "approved", "corrected_response": "ok"},
        {**_make_record("c"), "status": "discarded"},
        {**_make_record("d"), "status": "model_rejected"},
    ]
    _populate_candidates(tmp_path, records)
    write_jsonl(sft_module._approved_file(), [records[1]])
    r = client.get("/api/sft/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 4
    assert data["by_status"]["needs_review"] == 1
    assert data["by_status"]["approved"] == 1
    assert data["by_status"]["discarded"] == 1
    assert data["by_status"]["model_rejected"] == 1
    assert data["export_ready"] == 1


def test_stats_empty_when_no_data(client):
    r = client.get("/api/sft/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["export_ready"] == 0
