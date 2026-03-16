import json

import pytest
from app import api as api_module  # noqa: F401


@pytest.fixture(autouse=True)
def reset_globals(tmp_path):
    from app import api
    api.set_data_dir(tmp_path)
    api.reset_last_action()
    yield
    api.reset_last_action()


def test_import():
    from app import api  # noqa: F401


from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


@pytest.fixture
def queue_with_items():
    """Write 3 test emails to the queue file."""
    from app import api as api_module
    items = [
        {"id": f"id{i}", "subject": f"Subject {i}", "body": f"Body {i}",
         "from": "test@example.com", "date": "2026-03-01", "source": "imap:test"}
        for i in range(3)
    ]
    queue_path = api_module._DATA_DIR / "email_label_queue.jsonl"
    queue_path.write_text("\n".join(json.dumps(x) for x in items) + "\n")
    return items


def test_queue_returns_items(client, queue_with_items):
    r = client.get("/api/queue?limit=2")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3


def test_queue_empty_when_no_file(client):
    r = client.get("/api/queue")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


def test_label_appends_to_score(client, queue_with_items):
    from app import api as api_module
    r = client.post("/api/label", json={"id": "id0", "label": "interview_scheduled"})
    assert r.status_code == 200
    records = api_module._read_jsonl(api_module._score_file())
    assert len(records) == 1
    assert records[0]["id"] == "id0"
    assert records[0]["label"] == "interview_scheduled"
    assert "labeled_at" in records[0]

def test_label_removes_from_queue(client, queue_with_items):
    from app import api as api_module
    client.post("/api/label", json={"id": "id0", "label": "rejected"})
    queue = api_module._read_jsonl(api_module._queue_file())
    assert not any(x["id"] == "id0" for x in queue)

def test_label_unknown_id_returns_404(client, queue_with_items):
    r = client.post("/api/label", json={"id": "unknown", "label": "neutral"})
    assert r.status_code == 404

def test_skip_moves_to_back(client, queue_with_items):
    from app import api as api_module
    r = client.post("/api/skip", json={"id": "id0"})
    assert r.status_code == 200
    queue = api_module._read_jsonl(api_module._queue_file())
    assert queue[-1]["id"] == "id0"
    assert queue[0]["id"] == "id1"

def test_skip_unknown_id_returns_404(client, queue_with_items):
    r = client.post("/api/skip", json={"id": "nope"})
    assert r.status_code == 404


# --- Part A: POST /api/discard ---

def test_discard_writes_to_discarded_file(client, queue_with_items):
    from app import api as api_module
    r = client.post("/api/discard", json={"id": "id1"})
    assert r.status_code == 200
    discarded = api_module._read_jsonl(api_module._discarded_file())
    assert len(discarded) == 1
    assert discarded[0]["id"] == "id1"
    assert discarded[0]["label"] == "__discarded__"

def test_discard_removes_from_queue(client, queue_with_items):
    from app import api as api_module
    client.post("/api/discard", json={"id": "id1"})
    queue = api_module._read_jsonl(api_module._queue_file())
    assert not any(x["id"] == "id1" for x in queue)


# --- Part B: DELETE /api/label/undo ---

def test_undo_label_removes_from_score(client, queue_with_items):
    from app import api as api_module
    client.post("/api/label", json={"id": "id0", "label": "neutral"})
    r = client.delete("/api/label/undo")
    assert r.status_code == 200
    data = r.json()
    assert data["undone"]["type"] == "label"
    score = api_module._read_jsonl(api_module._score_file())
    assert score == []
    # Item should be restored to front of queue
    queue = api_module._read_jsonl(api_module._queue_file())
    assert queue[0]["id"] == "id0"

def test_undo_discard_removes_from_discarded(client, queue_with_items):
    from app import api as api_module
    client.post("/api/discard", json={"id": "id0"})
    r = client.delete("/api/label/undo")
    assert r.status_code == 200
    discarded = api_module._read_jsonl(api_module._discarded_file())
    assert discarded == []

def test_undo_skip_restores_to_front(client, queue_with_items):
    from app import api as api_module
    client.post("/api/skip", json={"id": "id0"})
    r = client.delete("/api/label/undo")
    assert r.status_code == 200
    queue = api_module._read_jsonl(api_module._queue_file())
    assert queue[0]["id"] == "id0"

def test_undo_with_no_action_returns_404(client):
    r = client.delete("/api/label/undo")
    assert r.status_code == 404


# --- Part C: GET /api/config/labels ---

def test_config_labels_returns_metadata(client):
    r = client.get("/api/config/labels")
    assert r.status_code == 200
    labels = r.json()
    assert len(labels) == 10
    assert labels[0]["key"] == "1"
    assert "emoji" in labels[0]
    assert "color" in labels[0]
    assert "name" in labels[0]


# ── /api/config ──────────────────────────────────────────────────────────────

@pytest.fixture
def config_dir(tmp_path):
    """Give the API a writable config directory."""
    from app import api as api_module
    api_module.set_config_dir(tmp_path)
    yield tmp_path
    api_module.set_config_dir(None)   # reset to default


@pytest.fixture
def data_dir():
    """Expose the current _DATA_DIR set by the autouse reset_globals fixture."""
    from app import api as api_module
    return api_module._DATA_DIR


def test_get_config_returns_empty_when_no_file(client, config_dir):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["accounts"] == []
    assert data["max_per_account"] == 500


def test_post_config_writes_yaml(client, config_dir):
    import yaml
    payload = {
        "accounts": [{"name": "Test", "host": "imap.test.com", "port": 993,
                       "use_ssl": True, "username": "u@t.com", "password": "pw",
                       "folder": "INBOX", "days_back": 30}],
        "max_per_account": 200,
    }
    r = client.post("/api/config", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    cfg_file = config_dir / "label_tool.yaml"
    assert cfg_file.exists()
    saved = yaml.safe_load(cfg_file.read_text())
    assert saved["max_per_account"] == 200
    assert saved["accounts"][0]["name"] == "Test"


def test_get_config_round_trips(client, config_dir):
    payload = {"accounts": [{"name": "R", "host": "h", "port": 993, "use_ssl": True,
                              "username": "u", "password": "p", "folder": "INBOX",
                              "days_back": 90}], "max_per_account": 300}
    client.post("/api/config", json=payload)
    r = client.get("/api/config")
    data = r.json()
    assert data["max_per_account"] == 300
    assert data["accounts"][0]["name"] == "R"


# ── /api/stats ───────────────────────────────────────────────────────────────

@pytest.fixture
def score_with_labels(tmp_path, data_dir):
    """Write a score file with 3 labels for stats tests."""
    score_path = data_dir / "email_score.jsonl"
    records = [
        {"id": "a", "label": "interview_scheduled"},
        {"id": "b", "label": "interview_scheduled"},
        {"id": "c", "label": "rejected"},
    ]
    score_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return records


def test_stats_returns_counts(client, score_with_labels):
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert data["counts"]["interview_scheduled"] == 2
    assert data["counts"]["rejected"] == 1


def test_stats_empty_when_no_file(client, data_dir):
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["counts"] == {}
    assert data["score_file_bytes"] == 0


def test_stats_download_returns_file(client, score_with_labels):
    r = client.get("/api/stats/download")
    assert r.status_code == 200
    assert "jsonlines" in r.headers.get("content-type", "")


def test_stats_download_404_when_no_file(client, data_dir):
    r = client.get("/api/stats/download")
    assert r.status_code == 404


# ── /api/accounts/test ───────────────────────────────────────────────────────

def test_account_test_missing_fields(client):
    r = client.post("/api/accounts/test", json={"account": {"host": "", "username": "", "password": ""}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "required" in data["message"].lower()


def test_account_test_success(client):
    from unittest.mock import MagicMock, patch
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"99"])
    with patch("app.imap_fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        r = client.post("/api/accounts/test", json={"account": {
            "host": "imap.example.com", "port": 993, "use_ssl": True,
            "username": "u@example.com", "password": "pw", "folder": "INBOX",
        }})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["count"] == 99


# ── /api/fetch/stream (SSE) ──────────────────────────────────────────────────

def _parse_sse(content: bytes) -> list[dict]:
    """Parse SSE response body into list of event dicts."""
    events = []
    for line in content.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_fetch_stream_no_accounts_configured(client, config_dir):
    """With no config, stream should immediately complete with 0 added."""
    r = client.get("/api/fetch/stream?accounts=NoSuchAccount&days_back=30&limit=10")
    assert r.status_code == 200
    events = _parse_sse(r.content)
    complete = next((e for e in events if e["type"] == "complete"), None)
    assert complete is not None
    assert complete["total_added"] == 0


def test_fetch_stream_with_mock_imap(client, config_dir, data_dir):
    """With one configured account, stream should yield start/done/complete events."""
    import yaml
    from unittest.mock import MagicMock, patch

    # Write a config with one account
    cfg = {"accounts": [{"name": "Mock", "host": "h", "port": 993, "use_ssl": True,
                          "username": "u", "password": "p", "folder": "INBOX",
                          "days_back": 30}], "max_per_account": 50}
    (config_dir / "label_tool.yaml").write_text(yaml.dump(cfg))

    raw_msg = (b"Subject: Interview\r\nFrom: a@b.com\r\n"
               b"Date: Mon, 1 Mar 2026 12:00:00 +0000\r\n\r\nBody")
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1"])
    mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {N})", raw_msg)])

    with patch("app.imap_fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        r = client.get("/api/fetch/stream?accounts=Mock&days_back=30&limit=50")

    assert r.status_code == 200
    events = _parse_sse(r.content)
    types = [e["type"] for e in events]
    assert "start" in types
    assert "done" in types
    assert "complete" in types


# ---- /api/finetune/status tests ----

def test_finetune_status_returns_empty_when_no_models_dir(client):
    """GET /api/finetune/status must return [] if models/ does not exist."""
    r = client.get("/api/finetune/status")
    assert r.status_code == 200
    assert r.json() == []


def test_finetune_status_returns_training_info(client, tmp_path):
    """GET /api/finetune/status must return one entry per training_info.json found."""
    import json as _json
    from app import api as api_module

    models_dir = tmp_path / "models" / "avocet-deberta-small"
    models_dir.mkdir(parents=True)
    info = {
        "name": "avocet-deberta-small",
        "base_model_id": "cross-encoder/nli-deberta-v3-small",
        "val_macro_f1": 0.712,
        "timestamp": "2026-03-15T12:00:00Z",
        "sample_count": 401,
    }
    (models_dir / "training_info.json").write_text(_json.dumps(info))

    api_module.set_models_dir(tmp_path / "models")
    try:
        r = client.get("/api/finetune/status")
        assert r.status_code == 200
        data = r.json()
        assert any(d["name"] == "avocet-deberta-small" for d in data)
    finally:
        api_module.set_models_dir(api_module._ROOT / "models")


def test_finetune_run_streams_sse_events(client):
    """GET /api/finetune/run must return text/event-stream content type."""
    from unittest.mock import patch, MagicMock

    mock_proc = MagicMock()
    mock_proc.stdout = iter(["Training epoch 1\n", "Done\n"])
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock()

    with patch("subprocess.Popen", return_value=mock_proc):
        r = client.get("/api/finetune/run?model=deberta-small&epochs=1")

    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")


def test_finetune_run_emits_complete_on_success(client):
    """GET /api/finetune/run must emit a complete event on clean exit."""
    from unittest.mock import patch, MagicMock

    mock_proc = MagicMock()
    mock_proc.stdout = iter(["progress line\n"])
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock()

    with patch("subprocess.Popen", return_value=mock_proc):
        r = client.get("/api/finetune/run?model=deberta-small&epochs=1")

    assert '{"type": "complete"}' in r.text


def test_finetune_run_emits_error_on_nonzero_exit(client):
    """GET /api/finetune/run must emit an error event on non-zero exit."""
    from unittest.mock import patch, MagicMock

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 1
    mock_proc.wait = MagicMock()

    with patch("subprocess.Popen", return_value=mock_proc):
        r = client.get("/api/finetune/run?model=deberta-small&epochs=1")

    assert '"type": "error"' in r.text


def test_finetune_run_passes_score_files_to_subprocess(client):
    """GET /api/finetune/run?score=file1&score=file2 must pass --score args to subprocess."""
    from unittest.mock import patch, MagicMock

    captured_cmd = []

    def mock_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        m = MagicMock()
        m.stdout = iter([])
        m.returncode = 0
        m.wait = MagicMock()
        return m

    with patch("subprocess.Popen", side_effect=mock_popen):
        client.get("/api/finetune/run?model=deberta-small&epochs=1&score=run1.jsonl&score=run2.jsonl")

    assert "--score" in captured_cmd
    assert captured_cmd.count("--score") == 2
    # Paths are resolved to absolute — check filenames are present as substrings
    assert any("run1.jsonl" in arg for arg in captured_cmd)
    assert any("run2.jsonl" in arg for arg in captured_cmd)


# ---- Cancel endpoint tests ----

def test_benchmark_cancel_returns_404_when_not_running(client):
    """POST /api/benchmark/cancel must return 404 if no benchmark is running."""
    from app import api as api_module
    api_module._running_procs.pop("benchmark", None)
    r = client.post("/api/benchmark/cancel")
    assert r.status_code == 404


def test_finetune_cancel_returns_404_when_not_running(client):
    """POST /api/finetune/cancel must return 404 if no finetune is running."""
    from app import api as api_module
    api_module._running_procs.pop("finetune", None)
    r = client.post("/api/finetune/cancel")
    assert r.status_code == 404


def test_benchmark_cancel_terminates_running_process(client):
    """POST /api/benchmark/cancel must call terminate() on the running process."""
    from unittest.mock import MagicMock
    from app import api as api_module

    mock_proc = MagicMock()
    mock_proc.wait = MagicMock()
    api_module._running_procs["benchmark"] = mock_proc

    try:
        r = client.post("/api/benchmark/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        mock_proc.terminate.assert_called_once()
    finally:
        api_module._running_procs.pop("benchmark", None)
        api_module._cancelled_jobs.discard("benchmark")


def test_finetune_cancel_terminates_running_process(client):
    """POST /api/finetune/cancel must call terminate() on the running process."""
    from unittest.mock import MagicMock
    from app import api as api_module

    mock_proc = MagicMock()
    mock_proc.wait = MagicMock()
    api_module._running_procs["finetune"] = mock_proc

    try:
        r = client.post("/api/finetune/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        mock_proc.terminate.assert_called_once()
    finally:
        api_module._running_procs.pop("finetune", None)
        api_module._cancelled_jobs.discard("finetune")


def test_benchmark_cancel_kills_process_on_timeout(client):
    """POST /api/benchmark/cancel must call kill() if the process does not exit within 3 s."""
    import subprocess
    from unittest.mock import MagicMock
    from app import api as api_module

    mock_proc = MagicMock()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="benchmark", timeout=3)
    api_module._running_procs["benchmark"] = mock_proc

    try:
        r = client.post("/api/benchmark/cancel")
        assert r.status_code == 200
        mock_proc.kill.assert_called_once()
    finally:
        api_module._running_procs.pop("benchmark", None)
        api_module._cancelled_jobs.discard("benchmark")


def test_finetune_run_emits_cancelled_event(client):
    """GET /api/finetune/run must emit cancelled (not error) when job was cancelled."""
    from unittest.mock import patch, MagicMock
    from app import api as api_module

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = -15  # SIGTERM

    def mock_popen(cmd, **kwargs):
        # Simulate cancel being called after process starts
        api_module._cancelled_jobs.add("finetune")
        return mock_proc

    try:
        with patch("subprocess.Popen", side_effect=mock_popen):
            r = client.get("/api/finetune/run?model=deberta-small&epochs=1")
        assert '{"type": "cancelled"}' in r.text
        assert '"type": "error"' not in r.text
    finally:
        api_module._cancelled_jobs.discard("finetune")


def test_benchmark_run_emits_cancelled_event(client):
    """GET /api/benchmark/run must emit cancelled (not error) when job was cancelled."""
    from unittest.mock import patch, MagicMock
    from app import api as api_module

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = -15

    def mock_popen(cmd, **kwargs):
        api_module._cancelled_jobs.add("benchmark")
        return mock_proc

    try:
        with patch("subprocess.Popen", side_effect=mock_popen):
            r = client.get("/api/benchmark/run")
        assert '{"type": "cancelled"}' in r.text
        assert '"type": "error"' not in r.text
    finally:
        api_module._cancelled_jobs.discard("benchmark")
