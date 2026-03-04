"""Avocet — IMAP fetch utilities.

Shared between app/api.py (FastAPI SSE endpoint) and app/label_tool.py (Streamlit).
No Streamlit imports here — stdlib + imaplib only.
"""
from __future__ import annotations

import email as _email_lib
import hashlib
import imaplib
import re
from datetime import datetime, timedelta
from email.header import decode_header as _raw_decode
from html.parser import HTMLParser
from typing import Any, Iterator


# ── HTML → plain text ────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(html_str: str) -> str:
    try:
        ex = _TextExtractor()
        ex.feed(html_str)
        return ex.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html_str).strip()


# ── IMAP decode helpers ───────────────────────────────────────────────────────

def _decode_str(value: str | None) -> str:
    if not value:
        return ""
    parts = _raw_decode(value)
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return " ".join(out).strip()


def _extract_body(msg: Any) -> str:
    if msg.is_multipart():
        html_fallback: str | None = None
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    charset = part.get_content_charset() or "utf-8"
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    pass
            elif ct == "text/html" and html_fallback is None:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    raw = part.get_payload(decode=True).decode(charset, errors="replace")
                    html_fallback = strip_html(raw)
                except Exception:
                    pass
        return html_fallback or ""
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            raw = msg.get_payload(decode=True).decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                return strip_html(raw)
            return raw
        except Exception:
            pass
    return ""


def entry_key(e: dict) -> str:
    """Stable MD5 content-hash for dedup — matches label_tool.py _entry_key."""
    key = (e.get("subject", "") + (e.get("body", "") or "")[:100])
    return hashlib.md5(key.encode("utf-8", errors="replace")).hexdigest()


# ── Wide search terms ────────────────────────────────────────────────────────

_WIDE_TERMS = [
    "interview", "phone screen", "video call", "zoom link", "schedule a call",
    "offer letter", "job offer", "offer of employment", "pleased to offer",
    "unfortunately", "not moving forward", "other candidates", "regret to inform",
    "no longer", "decided not to", "decided to go with",
    "opportunity", "interested in your background", "reached out", "great fit",
    "exciting role", "love to connect",
    "assessment", "questionnaire", "culture fit", "culture-fit", "online assessment",
    "application received", "thank you for applying", "application confirmation",
    "you applied", "your application for",
    "reschedule", "rescheduled", "new time", "moved to", "postponed", "new date",
    "job digest", "jobs you may like", "recommended jobs", "jobs for you",
    "new jobs", "job alert",
    "came across your profile", "reaching out about", "great fit for a role",
    "exciting opportunity",
    "welcome to the team", "start date", "onboarding", "first day", "we're excited to have you",
    "application", "recruiter", "recruiting", "hiring", "candidate",
]


# ── Public API ────────────────────────────────────────────────────────────────

def test_connection(acc: dict) -> tuple[bool, str, int | None]:
    """Connect, login, select folder. Returns (ok, human_message, message_count|None)."""
    host     = acc.get("host", "")
    port     = int(acc.get("port", 993))
    use_ssl  = acc.get("use_ssl", True)
    username = acc.get("username", "")
    password = acc.get("password", "")
    folder   = acc.get("folder", "INBOX")
    if not host or not username or not password:
        return False, "Host, username, and password are all required.", None
    try:
        conn = (imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4)(host, port)
        conn.login(username, password)
        _, data = conn.select(folder, readonly=True)
        count_raw = data[0].decode() if data and data[0] else "0"
        count = int(count_raw) if count_raw.isdigit() else 0
        conn.logout()
        return True, f"Connected — {count:,} message(s) in {folder}.", count
    except Exception as exc:
        return False, str(exc), None


def fetch_account_stream(
    acc: dict,
    days_back: int,
    limit: int,
    known_keys: set[str],
) -> Iterator[dict]:
    """Generator — yields progress dicts while fetching emails via IMAP.

    Mutates `known_keys` in place for cross-account dedup within one fetch session.

    Yields event dicts with "type" key:
        {"type": "start",    "account": str, "total_uids": int}
        {"type": "progress", "account": str, "fetched": int, "total_uids": int}
        {"type": "done",     "account": str, "added": int, "skipped": int, "emails": list}
    """
    name     = acc.get("name", acc.get("username", "?"))
    host     = acc.get("host", "imap.gmail.com")
    port     = int(acc.get("port", 993))
    use_ssl  = acc.get("use_ssl", True)
    username = acc["username"]
    password = acc["password"]
    folder   = acc.get("folder", "INBOX")
    since    = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")

    conn = (imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4)(host, port)
    conn.login(username, password)
    conn.select(folder, readonly=True)

    seen_uids: dict[bytes, None] = {}
    for term in _WIDE_TERMS:
        try:
            _, data = conn.search(None, f'(SUBJECT "{term}" SINCE "{since}")')
            for uid in (data[0] or b"").split():
                seen_uids[uid] = None
        except Exception:
            pass

    uids = list(seen_uids.keys())[: limit * 3]
    yield {"type": "start", "account": name, "total_uids": len(uids)}

    emails: list[dict] = []
    skipped = 0
    for i, uid in enumerate(uids):
        if len(emails) >= limit:
            break
        if i % 5 == 0:
            yield {"type": "progress", "account": name, "fetched": len(emails), "total_uids": len(uids)}
        try:
            _, raw_data = conn.fetch(uid, "(RFC822)")
            if not raw_data or not raw_data[0]:
                continue
            msg       = _email_lib.message_from_bytes(raw_data[0][1])
            subj      = _decode_str(msg.get("Subject", ""))
            from_addr = _decode_str(msg.get("From", ""))
            date      = _decode_str(msg.get("Date", ""))
            body      = _extract_body(msg)[:800]
            entry     = {"subject": subj, "body": body, "from_addr": from_addr,
                         "date": date, "account": name}
            k = entry_key(entry)
            if k not in known_keys:
                known_keys.add(k)
                emails.append(entry)
            else:
                skipped += 1
        except Exception:
            skipped += 1

    try:
        conn.logout()
    except Exception:
        pass

    yield {"type": "done", "account": name, "added": len(emails), "skipped": skipped,
           "emails": emails}
