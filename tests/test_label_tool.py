"""Tests for label_tool HTML extraction utilities.

These functions are stdlib-only and safe to test without an IMAP connection.
"""
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.utils import _extract_body, _strip_html


# ── _strip_html ──────────────────────────────────────────────────────────────

def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_skips_script_content():
    result = _strip_html("<script>doEvil()</script><p>real</p>")
    assert "doEvil" not in result
    assert "real" in result


def test_strip_html_skips_style_content():
    result = _strip_html("<style>.foo{color:red}</style><p>visible</p>")
    assert ".foo" not in result
    assert "visible" in result


def test_strip_html_handles_br_as_newline():
    result = _strip_html("line1<br>line2")
    assert "line1" in result
    assert "line2" in result


def test_strip_html_decodes_entities():
    # convert_charrefs=True on HTMLParser handles &amp; etc.
    result = _strip_html("<p>Hello &amp; welcome</p>")
    assert "&amp;" not in result
    assert "Hello" in result
    assert "welcome" in result


def test_strip_html_empty_string():
    assert _strip_html("") == ""


def test_strip_html_plain_text_passthrough():
    assert _strip_html("no tags here") == "no tags here"


# ── _extract_body ────────────────────────────────────────────────────────────

def test_extract_body_prefers_plain_over_html():
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("plain body", "plain"))
    msg.attach(MIMEText("<html><body>html body</body></html>", "html"))
    assert _extract_body(msg) == "plain body"


def test_extract_body_falls_back_to_html_when_no_plain():
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("<html><body><p>HTML only email</p></body></html>", "html"))
    result = _extract_body(msg)
    assert "HTML only email" in result
    assert "<" not in result  # no raw HTML tags leaked through


def test_extract_body_non_multipart_html_stripped():
    msg = MIMEText("<html><body><p>Solo HTML</p></body></html>", "html")
    result = _extract_body(msg)
    assert "Solo HTML" in result
    assert "<html>" not in result


def test_extract_body_non_multipart_plain_unchanged():
    msg = MIMEText("just plain text", "plain")
    assert _extract_body(msg) == "just plain text"


def test_extract_body_empty_message():
    msg = MIMEText("", "plain")
    assert _extract_body(msg) == ""


def test_extract_body_multipart_empty_returns_empty():
    msg = MIMEMultipart("alternative")
    assert _extract_body(msg) == ""
