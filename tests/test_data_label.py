"""Tests for app/data/label.py"""
import json
import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_globals(tmp_path):
    from app.data import label as label_module
    label_module.set_data_dir(tmp_path)
    label_module.set_config_dir(tmp_path)
    label_module.reset_last_action()
    yield
    label_module.reset_last_action()


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


@pytest.fixture
def queue_with_items(tmp_path):
    from app.data import label as label_module
    items = [
        {"id": f"id{i}", "subject": f"Subject {i}", "body": f"Body {i}",
         "from": "test@example.com", "date": "2026-03-01", "source": "imap:test"}
        for i in range(3)
    ]
    (label_module._DATA_DIR / "email_label_queue.jsonl").write_text(
        "\n".join(json.dumps(x) for x in items) + "\n")
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
    from app.data import label as label_module
    r = client.post("/api/label", json={"id": "id0", "label": "interview_scheduled"})
    assert r.status_code == 200
    records = label_module.read_jsonl(label_module._score_file())
    assert len(records) == 1
    assert records[0]["id"] == "id0"
    assert records[0]["label"] == "interview_scheduled"
    assert "labeled_at" in records[0]


def test_label_removes_from_queue(client, queue_with_items):
    from app.data import label as label_module
    client.post("/api/label", json={"id": "id0", "label": "rejected"})
    queue = label_module.read_jsonl(label_module._queue_file())
    assert not any(x["id"] == "id0" for x in queue)


def test_label_unknown_id_returns_404(client, queue_with_items):
    r = client.post("/api/label", json={"id": "unknown", "label": "neutral"})
    assert r.status_code == 404


def test_skip_moves_to_back(client, queue_with_items):
    from app.data import label as label_module
    r = client.post("/api/skip", json={"id": "id0"})
    assert r.status_code == 200
    queue = label_module.read_jsonl(label_module._queue_file())
    assert queue[-1]["id"] == "id0"
    assert queue[0]["id"] == "id1"


def test_skip_unknown_id_returns_404(client, queue_with_items):
    r = client.post("/api/skip", json={"id": "nope"})
    assert r.status_code == 404


def test_discard_writes_to_discarded_file(client, queue_with_items):
    from app.data import label as label_module
    r = client.post("/api/discard", json={"id": "id1"})
    assert r.status_code == 200
    discarded = label_module.read_jsonl(label_module._discarded_file())
    assert len(discarded) == 1
    assert discarded[0]["id"] == "id1"
    assert discarded[0]["label"] == "__discarded__"


def test_discard_removes_from_queue(client, queue_with_items):
    from app.data import label as label_module
    client.post("/api/discard", json={"id": "id1"})
    queue = label_module.read_jsonl(label_module._queue_file())
    assert not any(x["id"] == "id1" for x in queue)


def test_undo_label_removes_from_score(client, queue_with_items):
    from app.data import label as label_module
    client.post("/api/label", json={"id": "id0", "label": "neutral"})
    r = client.delete("/api/label/undo")
    assert r.status_code == 200
    assert r.json()["undone"]["type"] == "label"
    assert label_module.read_jsonl(label_module._score_file()) == []
    queue = label_module.read_jsonl(label_module._queue_file())
    assert queue[0]["id"] == "id0"


def test_undo_discard_removes_from_discarded(client, queue_with_items):
    from app.data import label as label_module
    client.post("/api/discard", json={"id": "id0"})
    r = client.delete("/api/label/undo")
    assert r.status_code == 200
    assert label_module.read_jsonl(label_module._discarded_file()) == []


def test_undo_skip_restores_to_front(client, queue_with_items):
    from app.data import label as label_module
    client.post("/api/skip", json={"id": "id0"})
    r = client.delete("/api/label/undo")
    assert r.status_code == 200
    queue = label_module.read_jsonl(label_module._queue_file())
    assert queue[0]["id"] == "id0"


def test_undo_with_no_action_returns_404(client):
    r = client.delete("/api/label/undo")
    assert r.status_code == 404


def test_config_labels_returns_10_labels(client):
    r = client.get("/api/config/labels")
    assert r.status_code == 200
    labels = r.json()
    assert len(labels) == 10
    assert labels[0]["key"] == "1"
    for lbl in labels:
        assert "emoji" in lbl and "color" in lbl and "name" in lbl


def test_get_config_returns_empty_when_no_file(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["accounts"] == []
    assert data["max_per_account"] == 500


def test_post_config_writes_yaml(client, tmp_path):
    from app.data import label as label_module
    label_module.set_config_dir(tmp_path)
    payload = {"accounts": [{"name": "Test", "host": "imap.test.com", "port": 993,
                              "use_ssl": True, "username": "u@t.com", "password": "pw",
                              "folder": "INBOX", "days_back": 30}], "max_per_account": 200}
    r = client.post("/api/config", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    saved = yaml.safe_load((tmp_path / "label_tool.yaml").read_text())
    assert saved["max_per_account"] == 200
    assert saved["accounts"][0]["name"] == "Test"


def test_get_config_round_trips(client, tmp_path):
    from app.data import label as label_module
    label_module.set_config_dir(tmp_path)
    payload = {"accounts": [{"name": "R", "host": "h", "port": 993, "use_ssl": True,
                              "username": "u", "password": "p", "folder": "INBOX",
                              "days_back": 90}], "max_per_account": 300}
    client.post("/api/config", json=payload)
    r = client.get("/api/config")
    data = r.json()
    assert data["max_per_account"] == 300
    assert data["accounts"][0]["name"] == "R"


def test_stats_returns_counts(client, tmp_path):
    from app.data import label as label_module
    label_module.set_data_dir(tmp_path)
    score_path = tmp_path / "email_score.jsonl"
    records = [{"id": "a", "label": "interview_scheduled"},
               {"id": "b", "label": "interview_scheduled"},
               {"id": "c", "label": "rejected"}]
    score_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert data["counts"]["interview_scheduled"] == 2
    assert data["counts"]["rejected"] == 1


def test_stats_empty_when_no_file(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["counts"] == {}
    assert data["score_file_bytes"] == 0


def test_stats_download_returns_file(client, tmp_path):
    from app.data import label as label_module
    label_module.set_data_dir(tmp_path)
    (tmp_path / "email_score.jsonl").write_text(json.dumps({"id": "a", "label": "neutral"}) + "\n")
    r = client.get("/api/stats/download")
    assert r.status_code == 200
    assert "jsonlines" in r.headers.get("content-type", "")


def test_stats_download_404_when_no_file(client):
    r = client.get("/api/stats/download")
    assert r.status_code == 404
