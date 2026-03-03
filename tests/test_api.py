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
def queue_with_items(tmp_path):
    """Write 3 test emails to the queue file."""
    from app import api as api_module
    items = [
        {"id": f"id{i}", "subject": f"Subject {i}", "body": f"Body {i}",
         "from": "test@example.com", "date": "2026-03-01", "source": "imap:test"}
        for i in range(3)
    ]
    queue_path = tmp_path / "email_label_queue.jsonl"
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
