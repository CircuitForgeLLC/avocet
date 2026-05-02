"""Smoke tests for the app factory (app/api.py).

Detailed route tests live in test_data_label.py, test_data_fetch.py,
test_data_corrections.py, test_train.py, and test_dashboard.py.
"""
import pytest
from fastapi.testclient import TestClient


def test_import():
    from app import api  # noqa: F401


def test_app_has_required_routes():
    from app.api import app
    paths = {r.path for r in app.routes}
    # Label routes
    assert "/api/queue" in paths
    assert "/api/label" in paths
    assert "/api/skip" in paths
    assert "/api/discard" in paths
    assert "/api/label/undo" in paths
    assert "/api/config/labels" in paths
    assert "/api/stats" in paths
    # Fetch routes
    assert "/api/accounts/test" in paths
    assert "/api/fetch/stream" in paths
    # Train routes
    assert "/api/train/jobs" in paths
    assert "/api/train/results" in paths


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def test_queue_endpoint_reachable(client):
    r = client.get("/api/queue")
    assert r.status_code == 200
    assert "items" in r.json()
    assert "total" in r.json()
