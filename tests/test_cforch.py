"""Tests for app/cforch.py — /api/cforch/* endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_cforch_globals(tmp_path):
    """Redirect _CONFIG_DIR to tmp_path, reset running-state globals, and stub
    list_installed to return [] so real disk model directories don't bleed into
    tests that don't exercise the installed-model merge path."""
    from app import cforch as cforch_module

    prev_config_dir = cforch_module._CONFIG_DIR
    prev_running = cforch_module._BENCH_RUNNING
    prev_proc = cforch_module._bench_proc

    cforch_module.set_config_dir(tmp_path)
    cforch_module._BENCH_RUNNING = False
    cforch_module._bench_proc = None

    with patch("app.models.list_installed", return_value=[]):
        yield tmp_path

    cforch_module.set_config_dir(prev_config_dir)
    cforch_module._BENCH_RUNNING = prev_running
    cforch_module._bench_proc = prev_proc


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


@pytest.fixture
def config_dir(reset_cforch_globals):
    """Return the tmp config dir (already set as _CONFIG_DIR)."""
    return reset_cforch_globals


def _write_config(config_dir: Path, cforch_cfg: dict) -> None:
    """Write a label_tool.yaml with the given cforch block into config_dir."""
    cfg = {"cforch": cforch_cfg}
    (config_dir / "label_tool.yaml").write_text(
        yaml.dump(cfg), encoding="utf-8"
    )


def _write_tasks_yaml(path: Path, tasks: list[dict]) -> None:
    path.write_text(yaml.dump({"tasks": tasks}), encoding="utf-8")


def _write_models_yaml(path: Path, models: list[dict]) -> None:
    path.write_text(yaml.dump({"models": models}), encoding="utf-8")


# ── GET /tasks ─────────────────────────────────────────────────────────────────

def test_tasks_returns_empty_when_not_configured(client):
    """No config file present — endpoint returns empty lists."""
    r = client.get("/api/cforch/tasks")
    assert r.status_code == 200
    data = r.json()
    assert data == {"tasks": [], "types": []}


def test_tasks_parses_yaml(client, config_dir, tmp_path):
    tasks_file = tmp_path / "bench_tasks.yaml"
    _write_tasks_yaml(tasks_file, [
        {"id": "t1", "name": "Task One", "type": "instruction"},
        {"id": "t2", "name": "Task Two", "type": "reasoning"},
    ])
    _write_config(config_dir, {"bench_tasks": str(tasks_file)})

    r = client.get("/api/cforch/tasks")
    assert r.status_code == 200
    data = r.json()
    assert len(data["tasks"]) == 2
    # TaskEntry now includes optional prompt/system fields (default "")
    t1 = data["tasks"][0]
    assert t1["id"] == "t1" and t1["name"] == "Task One" and t1["type"] == "instruction"
    t2 = data["tasks"][1]
    assert t2["id"] == "t2" and t2["name"] == "Task Two" and t2["type"] == "reasoning"
    assert "instruction" in data["types"]
    assert "reasoning" in data["types"]


def test_tasks_returns_types_deduplicated(client, config_dir, tmp_path):
    """Multiple tasks sharing a type — types list must not duplicate."""
    tasks_file = tmp_path / "bench_tasks.yaml"
    _write_tasks_yaml(tasks_file, [
        {"id": "t1", "name": "A", "type": "instruction"},
        {"id": "t2", "name": "B", "type": "instruction"},
        {"id": "t3", "name": "C", "type": "reasoning"},
    ])
    _write_config(config_dir, {"bench_tasks": str(tasks_file)})

    r = client.get("/api/cforch/tasks")
    data = r.json()
    assert data["types"].count("instruction") == 1
    assert len(data["types"]) == 2


# ── GET /models ────────────────────────────────────────────────────────────────

def test_models_returns_empty_when_not_configured(client):
    """No config file present — endpoint returns empty model list."""
    r = client.get("/api/cforch/models")
    assert r.status_code == 200
    assert r.json() == {"models": []}


def test_models_parses_bench_models_yaml(client, config_dir, tmp_path):
    models_file = tmp_path / "bench_models.yaml"
    _write_models_yaml(models_file, [
        {
            "name": "llama3",
            "id": "llama3:8b",
            "service": "ollama",
            "tags": ["fast", "small"],
            "vram_estimate_mb": 6000,
        }
    ])
    _write_config(config_dir, {"bench_models": str(models_file)})

    r = client.get("/api/cforch/models")
    assert r.status_code == 200
    data = r.json()
    assert len(data["models"]) == 1
    m = data["models"][0]
    assert m["name"] == "llama3"
    assert m["id"] == "llama3:8b"
    assert m["service"] == "ollama"
    assert m["tags"] == ["fast", "small"]
    assert m["vram_estimate_mb"] == 6000


def test_models_merges_installed_generators(client, config_dir, tmp_path):
    """Installed cf-text/vllm generator models appear in the model list,
    deduplicated against bench_models.yaml entries."""
    models_file = tmp_path / "bench_models.yaml"
    _write_models_yaml(models_file, [
        {"name": "llama3", "id": "llama3:8b", "service": "ollama", "tags": [], "vram_estimate_mb": 6000},
        {"name": "already-there", "id": "ibm-granite/granite-4.1-8b", "service": "cf-text", "tags": [], "vram_estimate_mb": 8000},
    ])
    _write_config(config_dir, {"bench_models": str(models_file)})

    fake_installed = [
        # should be included — cf-text generator not already in YAML
        {"model_id": "meta-llama/Llama-3.1-8B", "service": "cf-text", "role": "generator", "vram_mb": 16000},
        # should be deduped — repo_id matches a YAML entry
        {"model_id": "ibm-granite/granite-4.1-8b", "service": "cf-text", "role": "generator", "vram_mb": 8000},
        # should be excluded — classifier, not a generator
        {"model_id": "cross-encoder/ms-marco-MiniLM-L6", "service": "avocet", "role": "reranker", "vram_mb": 500},
    ]
    with patch("app.models.list_installed", return_value=fake_installed):
        r = client.get("/api/cforch/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["models"]]
    assert "llama3:8b" in ids                           # from YAML
    assert "ibm-granite/granite-4.1-8b" in ids          # from YAML (not duplicated)
    assert "meta-llama/Llama-3.1-8B" in ids             # merged from installed
    assert "cross-encoder/ms-marco-MiniLM-L6" not in ids  # filtered out (reranker)
    assert ids.count("ibm-granite/granite-4.1-8b") == 1  # no duplicate


# ── GET /run ───────────────────────────────────────────────────────────────────

def test_run_returns_409_when_already_running(client):
    """If a benchmark subprocess is actively running, GET /run returns 409."""
    from unittest.mock import MagicMock
    from app import cforch as cforch_module

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # process still alive
    cforch_module._BENCH_RUNNING = True
    cforch_module._bench_proc = mock_proc

    r = client.get("/api/cforch/run")
    assert r.status_code == 409


def test_run_returns_error_when_bench_script_not_configured(client):
    """No config at all — SSE stream contains an error event."""
    r = client.get("/api/cforch/run")
    assert r.status_code == 200
    assert '"type": "error"' in r.text
    assert "bench_script not configured" in r.text


def test_run_streams_progress_events(client, config_dir, tmp_path):
    """Mock subprocess — SSE stream emits progress events from stdout."""
    bench_script = tmp_path / "fake_benchmark.py"
    bench_script.write_text("# fake", encoding="utf-8")

    tasks_file = tmp_path / "bench_tasks.yaml"
    tasks_file.write_text(yaml.dump({"tasks": []}), encoding="utf-8")
    models_file = tmp_path / "bench_models.yaml"
    models_file.write_text(yaml.dump({"models": []}), encoding="utf-8")
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    _write_config(config_dir, {
        "bench_script": str(bench_script),
        "bench_tasks": str(tasks_file),
        "bench_models": str(models_file),
        "results_dir": str(results_dir),
        "python_bin": "/usr/bin/python3",
    })

    mock_stdout = MagicMock()
    mock_stdout.readline.side_effect = ["Running task 1\n", "Running task 2\n", ""]
    mock_proc = MagicMock()
    mock_proc.stdout = mock_stdout
    mock_proc.returncode = 1  # non-zero so we don't need summary.json
    mock_proc.wait = MagicMock()

    with patch("app.cforch._subprocess.Popen", return_value=mock_proc), \
         patch("app.cforch._select.select", return_value=([mock_stdout], [], [])):
        r = client.get("/api/cforch/run")

    assert r.status_code == 200
    assert '"type": "progress"' in r.text
    assert "Running task 1" in r.text
    assert "Running task 2" in r.text


def test_run_emits_result_on_success(client, config_dir, tmp_path):
    """Mock subprocess exit 0 + write fake summary.json — stream emits result event."""
    bench_script = tmp_path / "fake_benchmark.py"
    bench_script.write_text("# fake", encoding="utf-8")

    tasks_file = tmp_path / "bench_tasks.yaml"
    tasks_file.write_text(yaml.dump({"tasks": []}), encoding="utf-8")
    models_file = tmp_path / "bench_models.yaml"
    models_file.write_text(yaml.dump({"models": []}), encoding="utf-8")

    results_dir = tmp_path / "results"
    run_dir = results_dir / "2026-04-08-120000"
    run_dir.mkdir(parents=True)
    summary_data = {"score": 0.92, "models_evaluated": 3}
    (run_dir / "summary.json").write_text(json.dumps(summary_data), encoding="utf-8")

    _write_config(config_dir, {
        "bench_script": str(bench_script),
        "bench_tasks": str(tasks_file),
        "bench_models": str(models_file),
        "results_dir": str(results_dir),
        "python_bin": "/usr/bin/python3",
    })

    mock_stdout = MagicMock()
    mock_stdout.readline.side_effect = [""]  # no output lines, immediate EOF
    mock_proc = MagicMock()
    mock_proc.stdout = mock_stdout
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock()

    with patch("app.cforch._subprocess.Popen", return_value=mock_proc), \
         patch("app.cforch._select.select", return_value=([mock_stdout], [], [])):
        r = client.get("/api/cforch/run")

    assert r.status_code == 200
    assert '"type": "result"' in r.text
    assert '"score": 0.92' in r.text
    assert '"type": "complete"' in r.text


# ── GET /results ───────────────────────────────────────────────────────────────

def test_results_returns_404_when_no_results(client):
    """No results_dir configured — endpoint returns 404."""
    r = client.get("/api/cforch/results")
    assert r.status_code == 404


def test_results_returns_latest_summary(client, config_dir, tmp_path):
    """Write fake results dir with one subdir containing summary.json."""
    results_dir = tmp_path / "results"
    run_dir = results_dir / "2026-04-08-150000"
    run_dir.mkdir(parents=True)
    summary_data = {"score": 0.88, "run": "test"}
    (run_dir / "summary.json").write_text(json.dumps(summary_data), encoding="utf-8")

    _write_config(config_dir, {"results_dir": str(results_dir)})

    r = client.get("/api/cforch/results")
    assert r.status_code == 200
    data = r.json()
    assert data["score"] == 0.88
    assert data["run"] == "test"


# ── POST /cancel ───────────────────────────────────────────────────────────────

def test_cancel_returns_404_when_not_running(client):
    """POST /cancel when no benchmark running — returns 404."""
    r = client.post("/api/cforch/cancel")
    assert r.status_code == 404


def test_cancel_terminates_running_benchmark(client):
    """POST /cancel when benchmark is running — terminates proc and returns cancelled."""
    from app import cforch as cforch_module

    mock_proc = MagicMock()
    cforch_module._BENCH_RUNNING = True
    cforch_module._bench_proc = mock_proc

    r = client.post("/api/cforch/cancel")
    assert r.status_code == 200
    assert r.json() == {"status": "cancelled"}
    mock_proc.terminate.assert_called_once()
    assert cforch_module._BENCH_RUNNING is False
    assert cforch_module._bench_proc is None


# ── GET /config ────────────────────────────────────────────────────────────────

def test_config_returns_empty_when_no_yaml_no_env(client, monkeypatch):
    """No yaml, no env vars — all fields empty, license_key_set False."""
    for key in ("CF_ORCH_URL", "CF_LICENSE_KEY", "OLLAMA_HOST", "OLLAMA_MODEL"):
        monkeypatch.delenv(key, raising=False)

    r = client.get("/api/cforch/config")
    assert r.status_code == 200
    data = r.json()
    assert data["coordinator_url"] == ""
    assert data["ollama_url"] == ""
    assert data["license_key_set"] is False


def test_config_reads_env_vars_when_no_yaml(client, monkeypatch):
    """Env vars populate fields when label_tool.yaml has no cforch section."""
    monkeypatch.setenv("CF_ORCH_URL",      "http://orch.example.com:7700")
    monkeypatch.setenv("CF_LICENSE_KEY",   "CFG-AVCT-TEST-TEST-TEST")
    monkeypatch.setenv("OLLAMA_HOST",      "http://ollama.local:11434")
    monkeypatch.setenv("OLLAMA_MODEL",     "mistral:7b")

    r = client.get("/api/cforch/config")
    assert r.status_code == 200
    data = r.json()
    assert data["coordinator_url"] == "http://orch.example.com:7700"
    assert data["ollama_url"]      == "http://ollama.local:11434"
    assert data["ollama_model"]    == "mistral:7b"
    assert data["license_key_set"] is True   # set, but value not exposed


def test_config_yaml_overrides_env(client, config_dir, monkeypatch):
    """label_tool.yaml cforch values take priority over env vars."""
    monkeypatch.setenv("CF_ORCH_URL",  "http://env-orch:7700")
    monkeypatch.setenv("OLLAMA_HOST",  "http://env-ollama:11434")

    _write_config(config_dir, {
        "coordinator_url": "http://yaml-orch:7700",
        "ollama_url":      "http://yaml-ollama:11434",
    })

    r = client.get("/api/cforch/config")
    assert r.status_code == 200
    data = r.json()
    assert data["coordinator_url"] == "http://yaml-orch:7700"
    assert data["ollama_url"]      == "http://yaml-ollama:11434"
    assert data["source"] == "yaml+env"


def test_run_passes_license_key_env_to_subprocess(client, config_dir, tmp_path, monkeypatch):
    """CF_LICENSE_KEY must be forwarded to the benchmark subprocess env."""
    monkeypatch.setenv("CF_LICENSE_KEY", "CFG-AVCT-ENV-ONLY-KEY")

    bench_script = tmp_path / "benchmark.py"
    bench_script.write_text("# stub", encoding="utf-8")
    tasks_file   = tmp_path / "bench_tasks.yaml"
    tasks_file.write_text(yaml.dump({"tasks": []}), encoding="utf-8")
    models_file  = tmp_path / "bench_models.yaml"
    models_file.write_text(yaml.dump({"models": []}), encoding="utf-8")

    _write_config(config_dir, {
        "bench_script":  str(bench_script),
        "bench_tasks":   str(tasks_file),
        "bench_models":  str(models_file),
        "results_dir":   str(tmp_path / "results"),
        "python_bin":    "/usr/bin/python3",
    })

    captured_env: dict = {}

    def fake_popen(cmd, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        mock = MagicMock()
        mock.stdout = iter([])
        mock.returncode = 0
        mock.wait = MagicMock()
        return mock

    with patch("app.cforch._subprocess.Popen", side_effect=fake_popen):
        client.get("/api/cforch/run")

    assert captured_env.get("CF_LICENSE_KEY") == "CFG-AVCT-ENV-ONLY-KEY"


def test_eval_cforch_router_includes_all_sub_routers():
    """eval/cforch.py router must include routes from all four sub-routers."""
    from app.eval.cforch import router
    paths = {r.path for r in router.routes}
    assert any("/cforch/" in p for p in paths), f"no /cforch/ routes found in {paths}"
    assert any("/style/" in p for p in paths), f"no /style/ routes found in {paths}"
    assert any("/voice/" in p for p in paths), f"no /voice/ routes found in {paths}"
    assert any("/plans-bench/" in p for p in paths), f"no /plans-bench/ routes found in {paths}"
