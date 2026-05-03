"""Export circuitforge-plans/ documents as instruction-tuning JSONL pairs.

Each record is a HuggingFace chat-format example:

    {
      "id": "<sha256>",
      "messages": [
        {"role": "user", "content": "<reconstructed planning prompt>"},
        {"role": "assistant", "content": "<cleaned document content>"}
      ],
      "meta": {
        "source": "peregrine/2026-03-03-feedback-button-design.md",
        "product": "peregrine",
        "doc_type": "design",     # design | plan | spec | implementation | other
        "date": "2026-03-03",
        "paired_with": "...",     # sibling path, or null
        "word_count": 1847,
        "pair_role": "context"    # "context" | "target" | "standalone"
      }
    }

Pairing strategy
----------------
When a design doc and a plan doc share the same date + feature-name prefix,
they are treated as a pair:
  - design → plan: instruction = "Given this design doc, write the implementation plan."
    context appended = full design doc content.
  - Solo docs get a synthetic instruction from the title + first overview section.

Usage
-----
    # Preview stats and 5 sample records
    python scripts/export_plans.py --preview

    # Write full output
    python scripts/export_plans.py --output data/plan_pairs.jsonl

    # Restrict to specific products
    python scripts/export_plans.py --products peregrine,kiwi --output data/plan_pairs.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterator

# ── Paths ──────────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).parent
_AVOCET_ROOT = _SCRIPT_DIR.parent
_DEFAULT_PLANS_DIR = Path("/Library/Development/CircuitForge/circuitforge-plans")
_DEFAULT_OUTPUT = _AVOCET_ROOT / "data" / "plan_pairs.jsonl"

# ── Doc type detection ─────────────────────────────────────────────────────────

_TYPE_RE = re.compile(
    r"-(design|plan|spec|implementation|specs|plans)s?$",
    re.IGNORECASE,
)

_SKIP_DIRS = {"__pycache__", ".git", "node_modules"}

# Boilerplate lines to strip from document content before using as output.
_BOILERPLATE_RE = re.compile(
    r"""
    ^\s*>\s*\*\*For\s+agentic\s+workers.*         # superpowers agent hints
    |^\s*>\s*REQUIRED\s+SUB-SKILL.*
    |^\s*\*\*Date:\*\*.*                           # metadata header lines
    |\*\*Status:\*\*\s*Complete.*                  # completed-feature noise
    |\*\*Status:\*\*\s*Done.*
    |\*\*Product:\*\*.*
    |\*\*Repo:\*\*.*
    |\*\*Tech\s+Stack:\*\*.*
    |\*\*Candidate:\*\*.*                          # old synthetic personas
    |^Candidate:.*
    |^Team:.*
    """,
    re.VERBOSE | re.MULTILINE,
)

# Old repo/path names to normalise to current equivalents.
_PATH_NORMALIZATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"/devl/job-seeker", re.IGNORECASE),      "/Library/Development/CircuitForge/peregrine"),
    (re.compile(r"\bjob-seeker\b",   re.IGNORECASE),      "peregrine"),
    (re.compile(r"Alex Rivera",      re.IGNORECASE),      "[user]"),
]

# Instruction paraphrase templates per doc type.
# Each entry is (user_prefix, paired_prefix).
# {title}, {product}, {type_phrase}, {overview}, {design_context} are substituted.
_DESIGN_INSTRUCTIONS = [
    "Write a design document for {product}: {title}.\n\nContext: {overview}",
    "You are a software architect working on {product}. Draft a design spec for: {title}.\n\n{overview}",
    "Produce a CircuitForge-style design document for the following {product} feature — {title}.\n\nBackground: {overview}",
]

_PLAN_INSTRUCTIONS = [
    "Write an implementation plan for {product}: {title}.\n\nContext: {overview}",
    "Break the following {product} feature into a detailed implementation plan with file structure and task checkboxes — {title}.\n\n{overview}",
    "You are a senior engineer on {product}. Produce a step-by-step engineering plan for: {title}.\n\n{overview}",
]

_PAIRED_INSTRUCTIONS = [
    (
        "You are a software architect working on {product}, a CircuitForge product. "
        "Given the following design document, write a detailed implementation plan "
        "(file structure, task breakdown with checkboxes, migration steps if needed).\n\n"
        "---\n{design_context}\n---"
    ),
    (
        "The following is a design spec for a {product} feature. "
        "Produce a concrete implementation plan: file list, task checklist, any DB migrations needed.\n\n"
        "---\n{design_context}\n---"
    ),
    (
        "Convert this {product} design document into an actionable implementation plan. "
        "Include all files to create/modify, step-by-step tasks with checkboxes, and migration steps.\n\n"
        "---\n{design_context}\n---"
    ),
]


def _doc_type(stem: str) -> str:
    m = _TYPE_RE.search(stem)
    if not m:
        return "other"
    raw = m.group(1).lower().rstrip("s")
    return {"implementation": "plan"}.get(raw, raw)


def _date_feature(stem: str) -> tuple[str, str]:
    """Return (date, feature_slug) from '2026-03-03-feedback-button-design'."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+?)(?:-(design|plan|spec|implementation)s?)?$", stem, re.I)
    if m:
        return m.group(1), m.group(2)
    return "", stem


# ── Content extraction ─────────────────────────────────────────────────────────

def _extract_title(content: str) -> str:
    m = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_overview(content: str) -> str:
    """Return first substantive paragraph or h2 section body (≤300 chars)."""
    # Superpowers plans have an explicit **Goal:** line — prefer that.
    goal_m = re.search(r"\*\*Goal:\*\*\s*(.+)", content)
    if goal_m:
        return goal_m.group(1).strip()[:300]

    # Otherwise use the body of the first h2 section.
    h2_m = re.search(
        r"^##\s+\d*\.?\s*.+\n([\s\S]+?)(?=^##|\Z)",
        content,
        re.MULTILINE,
    )
    if h2_m:
        body = h2_m.group(1).strip()
        # Strip markdown bullet/code noise for the instruction
        body = re.sub(r"```[\s\S]*?```", "", body)
        body = re.sub(r"`[^`]+`", lambda m: m.group().strip("`"), body)
        body = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
        body = re.sub(r"\s+", " ", body).strip()
        return body[:300]

    return ""


def _clean_content(content: str) -> str:
    """Remove boilerplate, normalize old paths/names, collapse whitespace."""
    cleaned = _BOILERPLATE_RE.sub("", content)
    for pattern, replacement in _PATH_NORMALIZATIONS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _quality_flags(content: str) -> list[str]:
    """Return a list of quality issue labels found in cleaned content."""
    flags = []
    if "Alex Rivera" in content or "[user]" in content:
        flags.append("persona-residue")
    if re.search(r"\bStatus:\s*(Complete|Done|Merged)\b", content):
        flags.append("completed-status")
    return flags


def _make_instruction(
    title: str,
    product: str,
    doc_type: str,
    overview: str,
    design_context: str | None = None,
    variant: int = 0,
) -> str:
    """Synthesise a natural planning prompt for this document.

    variant: 0-2 selects which paraphrase template to use. Caller cycles
    through all three to produce multiple training examples per document.
    """
    product_label = product.replace("-", " ").title() if product else "CircuitForge"
    idx = variant % 3

    if design_context:
        tmpl = _PAIRED_INSTRUCTIONS[idx]
        return tmpl.format(
            product=product_label,
            design_context=design_context[:2500],
        )

    templates = _PLAN_INSTRUCTIONS if doc_type in ("plan",) else _DESIGN_INSTRUCTIONS
    tmpl = templates[idx]
    return tmpl.format(
        product=product_label,
        title=title,
        overview=overview or "",
        type_phrase="planning document",
    )


def _record_id(content: str, source: str) -> str:
    return hashlib.sha256(f"{source}:{content}".encode()).hexdigest()[:16]


# ── Pair discovery ─────────────────────────────────────────────────────────────

def _find_pairs(plans_dir: Path) -> dict[str, list[tuple[str, Path]]]:
    """Return {prefix_key → [(doc_type, path), ...]} for docs sharing date+feature."""
    by_prefix: dict[str, list[tuple[str, Path]]] = {}
    for path in plans_dir.rglob("*.md"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.name == "README.md":
            continue
        stem = path.stem
        date, feature = _date_feature(stem)
        if not date:
            continue
        key = str(path.parent / f"{date}-{feature}")
        by_prefix.setdefault(key, []).append((_doc_type(stem), path))
    return by_prefix


# ── Record generation ──────────────────────────────────────────────────────────

def _records_for_group(
    doc_type_paths: list[tuple[str, Path]],
    plans_dir: Path,
) -> Iterator[dict]:
    """Yield one or more training records for a group of related docs."""
    # Separate design vs plan docs within this group
    designs = [(t, p) for t, p in doc_type_paths if t in ("design", "spec")]
    plans_  = [(t, p) for t, p in doc_type_paths if t in ("plan",)]
    others  = [(t, p) for t, p in doc_type_paths if t not in ("design", "spec", "plan")]

    all_paths = doc_type_paths

    if designs and plans_:
        # Paired: yield a design→plan record (3 instruction variants)
        design_type, design_path = designs[0]
        plan_type,   plan_path   = plans_[0]
        design_content = design_path.read_text(encoding="utf-8")
        plan_content   = plan_path.read_text(encoding="utf-8")

        product        = _product_from_path(plan_path, plans_dir)
        title          = _extract_title(plan_content) or plan_path.stem
        cleaned        = _clean_content(plan_content)
        design_cleaned = _clean_content(design_content)
        flags          = _quality_flags(cleaned)

        if len(cleaned.split()) >= 80:
            rel_src    = str(plan_path.relative_to(plans_dir))
            rel_design = str(design_path.relative_to(plans_dir))
            for variant in range(3):
                instruction = _make_instruction(
                    title=title,
                    product=product,
                    doc_type="plan",
                    overview=_extract_overview(design_content),
                    design_context=design_cleaned,
                    variant=variant,
                )
                yield {
                    "id": _record_id(f"v{variant}:{cleaned}", rel_src),
                    "messages": [
                        {"role": "user", "content": instruction},
                        {"role": "assistant", "content": cleaned},
                    ],
                    "meta": {
                        "source": rel_src,
                        "product": product,
                        "doc_type": "plan",
                        "date": _date_feature(plan_path.stem)[0],
                        "paired_with": rel_design,
                        "word_count": len(cleaned.split()),
                        "pair_role": "target",
                        "variant": variant,
                        "quality_flags": flags,
                    },
                }

        # Also yield the design doc as standalone variants
        all_paths = [(t, p) for t, p in all_paths if p != plan_path]

    # Remaining docs as standalone records (3 instruction variants each)
    for doc_type, path in all_paths:
        content = path.read_text(encoding="utf-8")
        cleaned = _clean_content(content)
        if len(cleaned.split()) < 80:
            continue

        product  = _product_from_path(path, plans_dir)
        title    = _extract_title(content) or path.stem
        overview = _extract_overview(content)
        flags    = _quality_flags(cleaned)
        rel_src  = str(path.relative_to(plans_dir))

        for variant in range(3):
            instruction = _make_instruction(
                title=title,
                product=product,
                doc_type=doc_type,
                overview=overview,
                variant=variant,
            )
            yield {
                "id": _record_id(f"v{variant}:{cleaned}", rel_src),
                "messages": [
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": cleaned},
                ],
                "meta": {
                    "source": rel_src,
                    "product": product,
                    "doc_type": doc_type,
                    "date": _date_feature(path.stem)[0],
                    "paired_with": None,
                    "word_count": len(cleaned.split()),
                    "pair_role": "standalone",
                    "variant": variant,
                    "quality_flags": flags,
                },
            }


def _product_from_path(path: Path, plans_dir: Path) -> str:
    rel = path.relative_to(plans_dir)
    return rel.parts[0] if len(rel.parts) > 1 else "shared"


# ── Main export ────────────────────────────────────────────────────────────────

def export(
    plans_dir: Path,
    products: list[str] | None = None,
) -> list[dict]:
    groups = _find_pairs(plans_dir)
    records: list[dict] = []
    seen_ids: set[str] = set()

    for group_key, doc_type_paths in groups.items():
        # Filter by product if requested
        if products:
            paths = [p for _, p in doc_type_paths]
            prods = {_product_from_path(p, plans_dir) for p in paths}
            if not prods.intersection(products):
                continue

        for record in _records_for_group(doc_type_paths, plans_dir):
            if record["id"] not in seen_ids:
                seen_ids.add(record["id"])
                records.append(record)

    return records


# ── CLI ────────────────────────────────────────────────────────────────────────

def _print_stats(records: list[dict]) -> None:
    from collections import Counter
    products  = Counter(r["meta"]["product"]   for r in records)
    doc_types = Counter(r["meta"]["doc_type"]  for r in records)
    pair_roles = Counter(r["meta"]["pair_role"] for r in records)
    wc = [r["meta"]["word_count"] for r in records]
    wc.sort()

    print(f"\n{'='*55}")
    print(f"  Total records: {len(records)}")
    print(f"  Word counts  : min={wc[0]}, median={wc[len(wc)//2]}, max={wc[-1]}")
    print(f"\n  By product:")
    for p, n in products.most_common():
        print(f"    {p:<22} {n}")
    print(f"\n  By doc type:")
    for t, n in doc_types.most_common():
        print(f"    {t:<22} {n}")
    print(f"\n  Pair roles:")
    for r, n in pair_roles.most_common():
        print(f"    {r:<22} {n}")
    print(f"{'='*55}\n")


def _print_sample(records: list[dict], n: int = 3) -> None:
    import random
    sample = random.sample(records, min(n, len(records)))
    for i, rec in enumerate(sample, 1):
        meta = rec["meta"]
        user_msg = rec["messages"][0]["content"]
        asst_msg = rec["messages"][1]["content"]
        print(f"\n{'─'*55}")
        print(f"SAMPLE {i}/{n}  [{meta['product']} / {meta['doc_type']} / {meta['pair_role']}]")
        print(f"source: {meta['source']}")
        print(f"\nUSER ({len(user_msg)} chars):\n{user_msg[:500]}{'...' if len(user_msg)>500 else ''}")
        print(f"\nASSISTANT ({meta['word_count']} words):\n{asst_msg[:400]}{'...' if len(asst_msg)>400 else ''}")
    print(f"\n{'─'*55}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plans-dir", type=Path, default=_DEFAULT_PLANS_DIR)
    parser.add_argument("--output", type=Path, default=None,
                        help="Write JSONL to this path (omit for preview-only)")
    parser.add_argument("--products", default=None,
                        help="Comma-separated product filter, e.g. peregrine,kiwi")
    parser.add_argument("--preview", action="store_true",
                        help="Print stats + sample records, don't write output")
    parser.add_argument("--samples", type=int, default=3,
                        help="Number of sample records to show in preview (default 3)")
    args = parser.parse_args()

    products = [p.strip() for p in args.products.split(",")] if args.products else None

    print(f"Scanning {args.plans_dir} …", file=sys.stderr)
    records = export(args.plans_dir, products=products)

    _print_stats(records)

    if args.preview or args.output is None:
        _print_sample(records, n=args.samples)
        if args.output is None:
            print("(Pass --output <path> to write JSONL)")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
