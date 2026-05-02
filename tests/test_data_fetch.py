"""Tests for app/data/fetch.py"""
import json
import yaml
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_globals(tmp_path):
    from app.data import fetch as fetch_module
    fetch_module.set_data_dir(tmp_path)
    fetch_module.set_config_dir(tmp_path)
    yield


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def _parse_sse(content: bytes) -> list[dict]:
    events = []
    for line in content.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_account_test_missing_fields(client):
    r = client.post("/api/accounts/test",
                    json={"account": {"host": "", "username": "", "password": ""}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "required" in data["message"].lower()


def test_account_test_success(client):
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"99"])
    with patch("app.data.fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        r = client.post("/api/accounts/test", json={"account": {
            "host": "imap.example.com", "port": 993, "use_ssl": True,
            "username": "u@example.com", "password": "pw", "folder": "INBOX",
        }})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["count"] == 99


def test_fetch_stream_no_accounts_configured(client, tmp_path):
    r = client.get("/api/fetch/stream?accounts=NoSuchAccount&days_back=30&limit=10")
    assert r.status_code == 200
    events = _parse_sse(r.content)
    complete = next((e for e in events if e["type"] == "complete"), None)
    assert complete is not None
    assert complete["total_added"] == 0


def test_fetch_stream_with_mock_imap(client, tmp_path):
    from app.data import fetch as fetch_module
    fetch_module.set_config_dir(tmp_path)
    cfg = {"accounts": [{"name": "Mock", "host": "h", "port": 993, "use_ssl": True,
                         "username": "u", "password": "p", "folder": "INBOX",
                         "days_back": 30}], "max_per_account": 50}
    (tmp_path / "label_tool.yaml").write_text(yaml.dump(cfg))
    raw_msg = (b"Subject: Interview\r\nFrom: a@b.com\r\n"
               b"Date: Mon, 1 Mar 2026 12:00:00 +0000\r\n\r\nBody")
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1"])
    mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {N})", raw_msg)])
    with patch("app.data.fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        r = client.get("/api/fetch/stream?accounts=Mock&days_back=30&limit=50")
    assert r.status_code == 200
    events = _parse_sse(r.content)
    types = [e["type"] for e in events]
    assert "start" in types
    assert "done" in types
    assert "complete" in types


def test_entry_key_deterministic():
    from app.data.fetch import entry_key
    e = {"subject": "Test", "body": "Hello world"}
    assert entry_key(e) == entry_key(e)


def test_entry_key_differs_by_subject():
    from app.data.fetch import entry_key
    a = {"subject": "A", "body": "same body"}
    b = {"subject": "B", "body": "same body"}
    assert entry_key(a) != entry_key(b)
