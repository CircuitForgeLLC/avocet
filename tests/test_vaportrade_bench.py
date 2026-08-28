import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException
import pytest
import app.vaportrade_bench as vtb


def _app_with_router(tmp_path, monkeypatch):
    monkeypatch.setattr(vtb, "_RESULTS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(vtb.router, prefix="/api/vaportrade-bench")
    return TestClient(app)


def test_results_empty_when_no_runs(tmp_path, monkeypatch):
    client = _app_with_router(tmp_path, monkeypatch)
    r = client.get("/api/vaportrade-bench/results")
    assert r.status_code == 200
    assert r.json() == []


def test_results_latest_404_when_none(tmp_path, monkeypatch):
    client = _app_with_router(tmp_path, monkeypatch)
    r = client.get("/api/vaportrade-bench/results/latest")
    assert r.status_code == 404


def test_results_lists_a_real_report_file(tmp_path, monkeypatch):
    (tmp_path / "report-20260827-120000.md").write_text("# VaporTrade Cost/Load Report\n\nstuff")
    client = _app_with_router(tmp_path, monkeypatch)
    r = client.get("/api/vaportrade-bench/results")
    assert r.status_code == 200
    names = [row["filename"] for row in r.json()]
    assert "report-20260827-120000.md" in names


def test_run_rejects_unknown_kind(tmp_path, monkeypatch):
    client = _app_with_router(tmp_path, monkeypatch)
    r = client.get("/api/vaportrade-bench/run?kind=bogus")
    assert r.status_code == 400


def test_run_rejects_unconstrained_label(tmp_path, monkeypatch):
    client = _app_with_router(tmp_path, monkeypatch)
    r = client.get("/api/vaportrade-bench/run?kind=load&label=$(rm -rf /)")
    assert r.status_code == 422


def test_results_by_run_id_rejects_malformed_run_id(tmp_path, monkeypatch):
    client = _app_with_router(tmp_path, monkeypatch)
    r = client.get("/api/vaportrade-bench/results/not-a-report-id")
    assert r.status_code == 400


def test_build_command_load_csv_matches_make_report_glob():
    # bench/make_report.py (VaporTrade repo) globs load-*-single-*_stats.csv
    # / load-*-fleet-*_stats.csv -- the --csv prefix we build must produce a
    # filename Locust turns into something that glob actually matches, and
    # must carry a timestamp so concurrent/successive GUI runs don't clobber
    # each other's CSVs.
    cfg = {"repo_path": "/repo", "python_bin": "python3", "ssh_host": ""}
    cmd = vtb._build_command("load", 25, "single", cfg, "20260827-120000")
    csv_arg = cmd[cmd.index("--csv") + 1]
    assert csv_arg == "bench/results/load-20260827-120000-single-u25"
    # Locust appends "_stats.csv" to the --csv prefix.
    stats_filename = Path(csv_arg).name + "_stats.csv"
    assert re.fullmatch(r"load-.*-single-.*_stats\.csv", stats_filename)


def test_build_command_load_csv_varies_by_timestamp():
    cfg = {"repo_path": "/repo", "python_bin": "python3", "ssh_host": ""}
    cmd_a = vtb._build_command("load", 10, "fleet", cfg, "20260827-120000")
    cmd_b = vtb._build_command("load", 10, "fleet", cfg, "20260827-130000")
    csv_a = cmd_a[cmd_a.index("--csv") + 1]
    csv_b = cmd_b[cmd_b.index("--csv") + 1]
    assert csv_a != csv_b


def test_run_success_invokes_make_report_followup(tmp_path, monkeypatch):
    client = _app_with_router(tmp_path, monkeypatch)
    monkeypatch.setattr(
        vtb, "_load_config",
        lambda: {"repo_path": "/repo", "python_bin": "python3", "ssh_host": ""},
    )

    main_proc = MagicMock()
    main_proc.stdout = iter(["cost bench output\n"])
    main_proc.returncode = 0
    main_proc.wait = MagicMock()

    report_proc = MagicMock()
    report_proc.stdout = iter(["wrote report-20260827-120000.md\n"])
    report_proc.returncode = 0
    report_proc.wait = MagicMock()

    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return main_proc if len(calls) == 1 else report_proc

    with patch("app.vaportrade_bench._subprocess.Popen", side_effect=fake_popen):
        r = client.get("/api/vaportrade-bench/run?kind=cost")
    assert r.status_code == 200

    events = [
        json.loads(line[len("data: "):])
        for line in r.text.splitlines()
        if line.startswith("data: ")
    ]
    assert any(e["type"] == "complete" for e in events)
    assert any(
        e["type"] == "progress" and "generating report" in e["message"]
        for e in events
    )
    assert len(calls) == 2
    assert "bench/make_report.py" in calls[1]


def test_run_failure_skips_make_report_followup(tmp_path, monkeypatch):
    client = _app_with_router(tmp_path, monkeypatch)
    monkeypatch.setattr(
        vtb, "_load_config",
        lambda: {"repo_path": "/repo", "python_bin": "python3", "ssh_host": ""},
    )

    main_proc = MagicMock()
    main_proc.stdout = iter(["boom\n"])
    main_proc.returncode = 1
    main_proc.wait = MagicMock()

    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return main_proc

    with patch("app.vaportrade_bench._subprocess.Popen", side_effect=fake_popen):
        r = client.get("/api/vaportrade-bench/run?kind=cost")
    assert r.status_code == 200
    events = [
        json.loads(line[len("data: "):])
        for line in r.text.splitlines()
        if line.startswith("data: ")
    ]
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "complete" for e in events)
    assert len(calls) == 1  # make_report.py never invoked on a failed run


def test_results_by_run_id_rejects_path_traversal(tmp_path, monkeypatch):
    # FastAPI's default {run_id} path converter never matches a literal or
    # percent-encoded "/", so a traversal string routed through the real
    # HTTP layer 404s before reaching the handler at all -- that's already
    # safe, but doesn't exercise the handler's own defense-in-depth guard.
    # Call the handler directly (as a unit) to prove the guard itself
    # rejects a traversal-shaped run_id, independent of routing behavior.
    monkeypatch.setattr(vtb, "_RESULTS_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        vtb.get_results_by_run_id("report-../../../etc/passwd")
    assert exc_info.value.status_code == 400
