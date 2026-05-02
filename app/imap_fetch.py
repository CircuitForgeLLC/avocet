"""Backward-compat shim -- logic moved to app/data/fetch.py."""
import imaplib  # noqa: F401 -- re-exported so existing patch("app.imap_fetch.imaplib...") calls still work
from app.data.fetch import (  # noqa: F401
    entry_key,
    fetch_account_stream,
    test_connection,
    _decode_str,
    _WIDE_TERMS,
)
