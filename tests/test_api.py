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
