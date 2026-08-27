import json
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import FastAPI
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
