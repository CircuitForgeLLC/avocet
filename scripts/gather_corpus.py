#!/usr/bin/env python3
"""
Corpus gatherer for the voice benchmark fine-tune pipeline.

Pulls writing samples from multiple sources and drops .txt files into
data/voice_corpus/ in the format expected by benchmark_voice.py.

Sources:
  - Reddit: u/pyr0ball post history + comment history (public JSON API)
  - Campaign copy: claude-bridge/reddit-poster/campaigns/*.py (BODY strings)
  - Documents: brainmap, homeprojects notes, selected personal writing
  - Discord: requires manual export (see instructions below)

Usage:
    # Full gather (Reddit + local sources)
    conda run -n cf python scripts/gather_corpus.py

    # Reddit only
    conda run -n cf python scripts/gather_corpus.py --source reddit

    # Local files only (no network)
    conda run -n cf python scripts/gather_corpus.py --source local

    # Process a Discord data export zip
    conda run -n cf python scripts/gather_corpus.py --discord /path/to/discord-export.zip

Discord export instructions:
    Discord Settings → Privacy & Safety → Request all my data
    Wait for email, download zip, then run with --discord flag.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

# ------------------------------------------------------------------ #
# Paths
# ------------------------------------------------------------------ #

_ROOT = Path(__file__).parent.parent
_CORPUS_DIR = _ROOT / "data" / "style_corpus"
_CLAUDE_BRIDGE = Path("/Library/Development/CircuitForge/claude-bridge")
_DOCUMENTS = Path("/Library/Documents")

_REDDIT_USER = "pyr0ball"
_USER_AGENT = "Avocet/0.1 corpus-gatherer (CircuitForge; personal research)"
_REDDIT_BASE = "https://www.reddit.com"

# Minimum character length to include a sample (filters out one-liners)
_MIN_LENGTH = 80

# Phrases that suggest AI-generated content — skip these
_AI_TELLS = [
    "certainly!", "absolutely!", "great question", "i'd be happy to",
    "i apologize for", "it's worth noting", "in conclusion,",
    "feel free to reach out",
]


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _is_ai_generated(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _AI_TELLS)


def _clean(text: str) -> str:
    """Strip Reddit formatting artifacts and normalize whitespace."""
    text = re.sub(r"\[deleted\]|\[removed\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _write_corpus_file(filename: str, samples: list[str], source_label: str) -> None:
    """Write samples to a corpus .txt file with minimal separators."""
    path = _CORPUS_DIR / filename
    kept = [s for s in samples if len(s) >= _MIN_LENGTH and not _is_ai_generated(s)]
    if not kept:
        print(f"  [skip] {filename} — no samples passed filters")
        return
    separator = "\n\n---\n\n"
    path.write_text(separator.join(kept), encoding="utf-8")
    print(f"  [ok]   {filename} — {len(kept)} samples ({path.stat().st_size // 1024}KB)")


# ------------------------------------------------------------------ #
# Reddit source
# ------------------------------------------------------------------ #

def _reddit_fetch_page(
    client: httpx.Client,
    listing_type: str,
    after: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one page of a user's submitted posts or comments."""
    params: dict[str, Any] = {"limit": 100, "raw_json": 1}
    if after:
        params["after"] = after
    url = f"{_REDDIT_BASE}/user/{_REDDIT_USER}/{listing_type}.json"
    resp = client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    children = data["data"]["children"]
    new_after = data["data"].get("after")
    return [c["data"] for c in children], new_after


def _reddit_fetch_all(listing_type: str, max_items: int = 1000) -> list[dict[str, Any]]:
    """Paginate through a user listing until exhausted or max_items reached."""
    items: list[dict[str, Any]] = []
    after: str | None = None
    with httpx.Client(
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
        timeout=20.0,
    ) as client:
        while len(items) < max_items:
            try:
                page, after = _reddit_fetch_page(client, listing_type, after)
            except httpx.HTTPStatusError as exc:
                # Reddit blocks unauthenticated pagination after the first page;
                # save what we have rather than crashing.
                print(f"    stopped at {len(items)} {listing_type} (HTTP {exc.response.status_code})")
                break
            if not page:
                break
            items.extend(page)
            print(f"    fetched {len(items)} {listing_type}...")
            if not after:
                break
            time.sleep(1.0)  # respect rate limit
    return items


def gather_reddit() -> None:
    print("Fetching Reddit history for u/pyr0ball...")

    # Posts (submitted)
    print("  Posts:")
    posts = _reddit_fetch_all("submitted")
    post_texts: list[str] = []
    for p in posts:
        body = _clean(p.get("selftext", "") or "")
        title = _clean(p.get("title", ""))
        if len(body) >= _MIN_LENGTH:
            post_texts.append(f"{title}\n\n{body}")
        elif len(title) >= 20:
            # Title-only posts (link posts) — include title as micro-sample
            post_texts.append(title)
    _write_corpus_file("social_post_reddit.txt", post_texts, "reddit/submitted")

    # Comments
    print("  Comments:")
    comments = _reddit_fetch_all("comments")
    comment_texts: list[str] = []
    for c in comments:
        body = _clean(c.get("body", "") or "")
        if body and body not in ("[deleted]", "[removed]"):
            comment_texts.append(body)
    _write_corpus_file("social_reply_reddit_comments.txt", comment_texts, "reddit/comments")

    print(f"  Done. {len(posts)} posts, {len(comments)} comments fetched.")


# ------------------------------------------------------------------ #
# Campaign copy source (claude-bridge)
# ------------------------------------------------------------------ #

def _extract_body_from_campaign(py_file: Path) -> str | None:
    """
    Parse a campaign Python file and extract the BODY string literal.
    Uses AST to handle multi-line strings safely.
    """
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "BODY":
                        if isinstance(node.value, ast.Constant):
                            return str(node.value.value)
    except (SyntaxError, UnicodeDecodeError):
        pass
    return None


def gather_campaigns() -> None:
    campaigns_dir = _CLAUDE_BRIDGE / "reddit-poster" / "campaigns"
    if not campaigns_dir.exists():
        print(f"  [skip] campaigns dir not found: {campaigns_dir}")
        return

    print("Gathering campaign copy from claude-bridge...")
    samples: list[str] = []
    for py_file in sorted(campaigns_dir.glob("*.py")):
        body = _extract_body_from_campaign(py_file)
        if body:
            samples.append(body.strip())
            print(f"    {py_file.name} — {len(body)} chars")

    _write_corpus_file("narrative_campaign_copy.txt", samples, "claude-bridge/campaigns")


# ------------------------------------------------------------------ #
# Documents source
# ------------------------------------------------------------------ #

def gather_documents() -> None:
    print("Gathering local Documents...")
    samples: list[str] = []

    # brainmap — personal planning/thinking notes
    brainmap = _DOCUMENTS / "brainmap_v1.md"
    if brainmap.exists():
        text = _clean(brainmap.read_text(encoding="utf-8"))
        if len(text) >= _MIN_LENGTH:
            samples.append(text)
            print(f"    brainmap_v1.md — {len(text)} chars")

    # HomeProjects handoff notes — casual technical prose
    for handoff in sorted((_DOCUMENTS / "HomeProjects").glob("handoff*.md")):
        text = _clean(handoff.read_text(encoding="utf-8", errors="replace"))
        if len(text) >= _MIN_LENGTH:
            samples.append(text)
            print(f"    {handoff.name} — {len(text)} chars")

    # Personal letters (Closet folder) — intimate prose voice
    closet = _DOCUMENTS / "Closet"
    if closet.exists():
        for letter in closet.glob("*.md"):
            text = _clean(letter.read_text(encoding="utf-8", errors="replace"))
            if len(text) >= _MIN_LENGTH and not _is_ai_generated(text):
                samples.append(text)
                print(f"    {letter.name} — {len(text)} chars")

    _write_corpus_file("narrative_personal_docs.txt", samples, "documents")


# ------------------------------------------------------------------ #
# Discord export source
# ------------------------------------------------------------------ #

def gather_discord(export_zip: Path) -> None:
    """
    Process a Discord data export zip (from Settings → Privacy & Safety → Request all my data).

    Expected zip structure:
        messages/
          c{channel_id}/
            messages.json   -- list of {ID, Timestamp, Contents, Attachments}
        account/
          user.json         -- {username, ...}
    """
    print(f"Processing Discord export: {export_zip}")
    samples: list[str] = []
    message_count = 0

    with zipfile.ZipFile(export_zip) as zf:
        # Find all messages.json files
        message_files = [n for n in zf.namelist() if n.endswith("/messages.json")]
        print(f"  Found {len(message_files)} channel(s)")

        for mf in message_files:
            try:
                data = json.loads(zf.read(mf))
            except (json.JSONDecodeError, KeyError):
                continue

            for msg in data:
                content = _clean(msg.get("Contents", "") or "")
                # Skip system messages, bot commands, very short messages
                if (
                    len(content) < _MIN_LENGTH
                    or content.startswith("/")
                    or content.startswith("!")
                    or _is_ai_generated(content)
                ):
                    continue
                # Skip messages that are just URLs or attachments
                if re.match(r"^https?://\S+$", content):
                    continue
                samples.append(content)
                message_count += 1

    print(f"  {message_count} messages → {len(samples)} passed filters")
    _write_corpus_file("social_reply_discord.txt", samples, "discord")


# ------------------------------------------------------------------ #
# Entrypoint
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(description="Gather writing corpus for voice benchmark")
    parser.add_argument(
        "--source",
        choices=["reddit", "local", "all"],
        default="all",
        help="Which sources to gather (default: all)",
    )
    parser.add_argument(
        "--discord",
        type=Path,
        metavar="ZIP",
        help="Path to Discord data export zip",
    )
    args = parser.parse_args()

    _CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output: {_CORPUS_DIR}\n")

    if args.source in ("reddit", "all"):
        gather_reddit()
        print()

    if args.source in ("local", "all"):
        gather_campaigns()
        print()
        gather_documents()
        print()

    if args.discord:
        if not args.discord.exists():
            print(f"Error: Discord export not found: {args.discord}")
        else:
            gather_discord(args.discord)
            print()

    if not args.discord and args.source in ("local", "all"):
        print("Discord: manual step required")
        print("  1. Discord Settings → Privacy & Safety → Request all my data")
        print("  2. Download the zip from the email link")
        print("  3. Run: python scripts/gather_corpus.py --discord /path/to/package.zip")
        print()

    # Summary
    corpus_files = sorted(_CORPUS_DIR.glob("*.txt"))
    total_chars = sum(f.stat().st_size for f in corpus_files)
    print(f"Corpus: {len(corpus_files)} file(s), {total_chars // 1024}KB total")
    for f in corpus_files:
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
