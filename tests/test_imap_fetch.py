"""Tests for imap_fetch — IMAP calls mocked."""
from unittest.mock import MagicMock, patch


def test_test_connection_missing_fields():
    from app.imap_fetch import test_connection
    ok, msg, count = test_connection({"host": "", "username": "", "password": ""})
    assert ok is False
    assert "required" in msg.lower()


def test_test_connection_success():
    from app.imap_fetch import test_connection

    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"42"])

    with patch("app.imap_fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        ok, msg, count = test_connection({
            "host": "imap.example.com", "port": 993, "use_ssl": True,
            "username": "u@example.com", "password": "secret", "folder": "INBOX",
        })
    assert ok is True
    assert count == 42
    assert "42" in msg


def test_test_connection_auth_failure():
    from app.imap_fetch import test_connection
    import imaplib

    with patch("app.imap_fetch.imaplib.IMAP4_SSL", side_effect=imaplib.IMAP4.error("auth failed")):
        ok, msg, count = test_connection({
            "host": "imap.example.com", "port": 993, "use_ssl": True,
            "username": "u@example.com", "password": "wrong", "folder": "INBOX",
        })
    assert ok is False
    assert count is None


def test_fetch_account_stream_yields_start_done(tmp_path):
    from app.imap_fetch import fetch_account_stream

    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2"])
    raw_msg = b"Subject: Test\r\nFrom: a@b.com\r\nDate: Mon, 1 Mar 2026 12:00:00 +0000\r\n\r\nHello"
    mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {N})", raw_msg)])

    with patch("app.imap_fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        events = list(fetch_account_stream(
            acc={"host": "h", "port": 993, "use_ssl": True,
                 "username": "u", "password": "p", "folder": "INBOX", "name": "Test"},
            days_back=30, limit=10, known_keys=set(),
        ))

    types = [e["type"] for e in events]
    assert "start" in types
    assert "done" in types


def test_fetch_account_stream_deduplicates(tmp_path):
    from app.imap_fetch import fetch_account_stream

    raw_msg = b"Subject: Dupe\r\nFrom: a@b.com\r\nDate: Mon, 1 Mar 2026 12:00:00 +0000\r\n\r\nBody"
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1"])
    mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {N})", raw_msg)])

    known = set()
    with patch("app.imap_fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        events1 = list(fetch_account_stream(
            {"host": "h", "port": 993, "use_ssl": True, "username": "u",
             "password": "p", "folder": "INBOX", "name": "T"},
            30, 10, known,
        ))
    done1 = next(e for e in events1 if e["type"] == "done")

    with patch("app.imap_fetch.imaplib.IMAP4_SSL", return_value=mock_conn):
        events2 = list(fetch_account_stream(
            {"host": "h", "port": 993, "use_ssl": True, "username": "u",
             "password": "p", "folder": "INBOX", "name": "T"},
            30, 10, known,
        ))
    done2 = next(e for e in events2 if e["type"] == "done")
    assert done1["added"] == 1
    assert done2["added"] == 0
