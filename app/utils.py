"""Shared email utility functions for Avocet.

Pure-stdlib helpers extracted from the retired label_tool.py Streamlit app.
These are reused by the FastAPI backend and the test suite.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


# ── HTML → plain-text extractor ──────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Extract visible text from an HTML email body, preserving line breaks."""
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
    _SKIP  = {"script", "style", "head", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._depth_skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._SKIP:
            self._depth_skip += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self._SKIP:
            self._depth_skip = max(0, self._depth_skip - 1)

    def handle_data(self, data):
        if not self._depth_skip:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def strip_html(html_str: str) -> str:
    """Convert HTML email body to plain text. Pure stdlib, no dependencies."""
    try:
        extractor = _TextExtractor()
        extractor.feed(html_str)
        return extractor.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html_str).strip()


def extract_body(msg: Any) -> str:
    """Return plain-text body. Strips HTML when no text/plain part exists."""
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


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, returning valid records. Skips blank lines and malformed JSON."""
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write records to a JSONL file, overwriting any existing content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(r) for r in records)
    path.write_text(content + ("\n" if records else ""), encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    """Append a single record to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
