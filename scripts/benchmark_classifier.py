#!/usr/bin/env python
"""
Email classifier benchmark — compare HuggingFace models against our 6 labels.

Usage:
    # List available models
    conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --list-models

    # Score against labeled JSONL
    conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --score

    # Visual comparison on live IMAP emails (uses first account in label_tool.yaml)
    conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --compare --limit 20

    # Include slow/large models
    conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --score --include-slow

    # Export DB-labeled emails (⚠️ LLM-generated labels)
    conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --export-db --db /path/to/staging.db
"""
from __future__ import annotations

import argparse
import email as _email_lib
import imaplib
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

_ROOT = Path(__file__).parent.parent
_MODELS_DIR = _ROOT / "models"

from scripts.classifier_adapters import (
    LABELS,
    LABEL_DESCRIPTIONS,
    ClassifierAdapter,
    FineTunedAdapter,
    GLiClassAdapter,
    RerankerAdapter,
    ZeroShotAdapter,
    compute_metrics,
)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "deberta-zeroshot": {
        "adapter": ZeroShotAdapter,
        "model_id": "MoritzLaurer/DeBERTa-v3-large-zeroshot-v2.0",
        "params": "400M",
        "default": True,
    },
    "deberta-small": {
        "adapter": ZeroShotAdapter,
        "model_id": "cross-encoder/nli-deberta-v3-small",
        "params": "100M",
        "default": True,
    },
    "gliclass-large": {
        "adapter": GLiClassAdapter,
        "model_id": "knowledgator/gliclass-instruct-large-v1.0",
        "params": "400M",
        "default": True,
    },
    "bart-mnli": {
        "adapter": ZeroShotAdapter,
        "model_id": "facebook/bart-large-mnli",
        "params": "400M",
        "default": True,
    },
    "bge-m3-zeroshot": {
        "adapter": ZeroShotAdapter,
        "model_id": "MoritzLaurer/bge-m3-zeroshot-v2.0",
        "params": "600M",
        "default": True,
    },
    "deberta-small-2pass": {
        "adapter": ZeroShotAdapter,
        "model_id": "cross-encoder/nli-deberta-v3-small",
        "params": "100M",
        "default": True,
        "kwargs": {"two_pass": True},
    },
    "deberta-base-anli": {
        "adapter": ZeroShotAdapter,
        "model_id": "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",
        "params": "200M",
        "default": True,
    },
    "deberta-large-ling": {
        "adapter": ZeroShotAdapter,
        "model_id": "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli",
        "params": "400M",
        "default": False,
    },
    "mdeberta-xnli-2m": {
        "adapter": ZeroShotAdapter,
        "model_id": "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        "params": "300M",
        "default": False,
    },
    "bge-reranker": {
        "adapter": RerankerAdapter,
        "model_id": "BAAI/bge-reranker-v2-m3",
        "params": "600M",
        "default": False,
    },
    "deberta-xlarge": {
        "adapter": ZeroShotAdapter,
        "model_id": "microsoft/deberta-xlarge-mnli",
        "params": "750M",
        "default": False,
    },
    "mdeberta-mnli": {
        "adapter": ZeroShotAdapter,
        "model_id": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        "params": "300M",
        "default": False,
    },
    "xlm-roberta-anli": {
        "adapter": ZeroShotAdapter,
        "model_id": "vicgalle/xlm-roberta-large-xnli-anli",
        "params": "600M",
        "default": False,
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_scoring_jsonl(path: str) -> list[dict[str, str]]:
    """Load labeled examples from a JSONL file for benchmark scoring."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Scoring file not found: {path}\n"
            f"Copy data/email_score.jsonl.example → data/email_score.jsonl "
            f"or use the label tool (app/label_tool.py) to label your own emails."
        )
    rows = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def discover_finetuned_models(models_dir: Path | None = None) -> list[dict]:
    """Scan models/ for subdirs containing training_info.json.

    Returns a list of training_info dicts, each with an added 'model_dir' key.
    Returns [] silently if models_dir does not exist.
    """
    if models_dir is None:
        models_dir = _MODELS_DIR
    if not models_dir.exists():
        return []
    found = []
    for sub in models_dir.iterdir():
        if not sub.is_dir():
            continue
        info_path = sub / "training_info.json"
        if not info_path.exists():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[discover] WARN: skipping {info_path}: {exc}", flush=True)
            continue
        if "name" not in info:
            print(f"[discover] WARN: skipping {info_path}: missing 'name' key", flush=True)
            continue
        info["model_dir"] = str(sub)
        found.append(info)
    return found


def build_exemplars_from_jsonl(path: str, k_per_label: int = 10) -> dict[str, list[str]]:
    """Sample up to k_per_label formatted email texts per label from a scored JSONL.

    Formats each row as 'Subject: {subject}\n\n{body[:600]}' — the same format
    EmbeddingKNNAdapter uses at classify() time.  Rows missing the 'label' key
    are skipped silently.

    Returns dict[label, list[str]] ready for EmbeddingKNNAdapter(exemplar_texts=...).
    """
    result: dict[str, list[str]] = {}
    p = Path(path)
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[build_exemplars] WARN: skipping malformed line: {exc}", flush=True)
                continue
            label = row.get("label")
            if not label:
                continue
            subject = row.get("subject", "")
            body = row.get("body", "")
            if not subject and not body:
                continue
            texts = result.setdefault(label, [])
            if len(texts) < k_per_label:
                texts.append(
                    f"Subject: {subject}\n\n{body[:600]}"
                )
    return result


def _active_models(include_slow: bool = False) -> dict[str, dict[str, Any]]:
    """Return the active model registry, merged with any discovered fine-tuned models."""
    active: dict[str, dict[str, Any]] = {
        key: {**entry, "adapter_instance": entry["adapter"](
            key,
            entry["model_id"],
            **entry.get("kwargs", {}),
        )}
        for key, entry in MODEL_REGISTRY.items()
        if include_slow or entry.get("default", False)
    }
    for info in discover_finetuned_models():
        name = info["name"]
        active[name] = {
            "adapter_instance": FineTunedAdapter(name, info["model_dir"]),
            "params": "fine-tuned",
            "default": True,
        }
    return active


def run_scoring(
    adapters: list[ClassifierAdapter],
    score_file: str,
) -> dict[str, Any]:
    """Run all adapters against a labeled JSONL. Returns per-adapter metrics."""
    rows = load_scoring_jsonl(score_file)
    gold = [r["label"] for r in rows]
    results: dict[str, Any] = {}

    for i, adapter in enumerate(adapters, 1):
        print(f"[{i}/{len(adapters)}] Running {adapter.name} ({len(rows)} samples) …", flush=True)
        preds: list[str] = []
        t0 = time.monotonic()
        for row in rows:
            try:
                pred = adapter.classify(row["subject"], row["body"])
            except Exception as exc:
                print(f"  [{adapter.name}] ERROR on '{row['subject'][:40]}': {exc}", flush=True)
                pred = "neutral"
            preds.append(pred)
        elapsed_ms = (time.monotonic() - t0) * 1000
        metrics = compute_metrics(preds, gold, LABELS)
        metrics["latency_ms"] = round(elapsed_ms / len(rows), 1)
        results[adapter.name] = metrics
        print(f"  → macro-F1 {metrics['__macro_f1__']:.3f}  accuracy {metrics['__accuracy__']:.3f}  {metrics['latency_ms']:.1f} ms/email", flush=True)
        adapter.unload()

    return results


# ---------------------------------------------------------------------------
# IMAP helpers (stdlib only — reads label_tool.yaml, uses first account)
# ---------------------------------------------------------------------------

_BROAD_TERMS = [
    "interview", "opportunity", "offer letter",
    "job offer", "application", "recruiting",
]


def _load_imap_config() -> dict[str, Any]:
    """Load IMAP config from label_tool.yaml, returning first account as a flat dict."""
    import yaml
    cfg_path = Path(__file__).parent.parent / "config" / "label_tool.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"IMAP config not found: {cfg_path}\n"
            f"Copy config/label_tool.yaml.example → config/label_tool.yaml"
        )
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    accounts = cfg.get("accounts", [])
    if not accounts:
        raise ValueError("No accounts configured in config/label_tool.yaml")
    return accounts[0]


def _imap_connect(cfg: dict[str, Any]) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(cfg["host"], cfg.get("port", 993))
    conn.login(cfg["username"], cfg["password"])
    return conn


def _decode_part(part: Any) -> str:
    charset = part.get_content_charset() or "utf-8"
    try:
        return part.get_payload(decode=True).decode(charset, errors="replace")
    except Exception:
        return ""


def _parse_uid(conn: imaplib.IMAP4_SSL, uid: bytes) -> dict[str, str] | None:
    try:
        _, data = conn.uid("fetch", uid, "(RFC822)")
        raw = data[0][1]
        msg = _email_lib.message_from_bytes(raw)
        subject = str(msg.get("subject", "")).strip()
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = _decode_part(part)
                    break
        else:
            body = _decode_part(msg)
        return {"subject": subject, "body": body}
    except Exception:
        return None


def _fetch_imap_sample(limit: int, days: int) -> list[dict[str, str]]:
    cfg = _load_imap_config()
    conn = _imap_connect(cfg)
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    conn.select("INBOX")

    seen_uids: dict[bytes, None] = {}
    for term in _BROAD_TERMS:
        _, data = conn.uid("search", None, f'(SUBJECT "{term}" SINCE {since})')
        for uid in (data[0] or b"").split():
            seen_uids[uid] = None

    sample = list(seen_uids.keys())[:limit]
    emails = []
    for uid in sample:
        parsed = _parse_uid(conn, uid)
        if parsed:
            emails.append(parsed)
    try:
        conn.logout()
    except Exception:
        pass
    return emails


# ---------------------------------------------------------------------------
# DB export
# ---------------------------------------------------------------------------

def cmd_export_db(args: argparse.Namespace) -> None:
    """Export LLM-labeled emails from a peregrine-style job_contacts table → scoring JSONL."""
    import sqlite3

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT subject, body, stage_signal
        FROM job_contacts
        WHERE stage_signal IS NOT NULL
          AND stage_signal != ''
          AND direction = 'inbound'
        ORDER BY received_at
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No labeled emails in job_contacts. Run imap_sync first to populate.")
        return

    out_path = Path(args.score_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    label_counts: dict[str, int] = {}
    with out_path.open("w") as f:
        for subject, body, label in rows:
            if label not in LABELS:
                print(f"  SKIP unknown label '{label}': {subject[:50]}")
                skipped += 1
                continue
            json.dump({"subject": subject or "", "body": (body or "")[:600], "label": label}, f)
            f.write("\n")
            label_counts[label] = label_counts.get(label, 0) + 1
            written += 1

    print(f"\nExported {written} emails → {out_path}" + (f" ({skipped} skipped)" if skipped else ""))
    print("\nLabel distribution:")
    for label in LABELS:
        count = label_counts.get(label, 0)
        bar = "█" * count
        print(f"  {label:<25} {count:>3}  {bar}")
    print(
        "\nNOTE: Labels are LLM predictions from imap_sync — review before treating as ground truth."
    )


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_list_models(_args: argparse.Namespace) -> None:
    print(f"\n{'Name':<24} {'Params':<8} {'Default':<20} {'Adapter':<15} Model ID")
    print("-" * 104)
    for name, entry in MODEL_REGISTRY.items():
        adapter_name = entry["adapter"].__name__
        if entry.get("kwargs", {}).get("two_pass"):
            adapter_name += " (2-pass)"
        default_flag = "yes" if entry["default"] else "(--include-slow)"
        print(f"{name:<24} {entry['params']:<8} {default_flag:<20} {adapter_name:<15} {entry['model_id']}")
    print()


def cmd_score(args: argparse.Namespace) -> None:
    active = _active_models(args.include_slow)
    if args.models:
        active = {k: v for k, v in active.items() if k in args.models}

    adapters = [entry["adapter_instance"] for entry in active.values()]

    print(f"\nScoring {len(adapters)} model(s) against {args.score_file} …\n")
    results = run_scoring(adapters, args.score_file)

    col = 12
    print(f"{'Model':<22}" + f"{'macro-F1':>{col}} {'Accuracy':>{col}} {'ms/email':>{col}}")
    print("-" * (22 + col * 3 + 2))
    for name, m in results.items():
        print(
            f"{name:<22}"
            f"{m['__macro_f1__']:>{col}.3f}"
            f"{m['__accuracy__']:>{col}.3f}"
            f"{m['latency_ms']:>{col}.1f}"
        )

    print("\nPer-label F1:")
    names = list(results.keys())
    print(f"{'Label':<25}" + "".join(f"{n[:11]:>{col}}" for n in names))
    print("-" * (25 + col * len(names)))
    for label in LABELS:
        row_str = f"{label:<25}"
        for m in results.values():
            row_str += f"{m[label]['f1']:>{col}.3f}"
        print(row_str)
    print()

    if args.save:
        import datetime
        rows = load_scoring_jsonl(args.score_file)
        save_data = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "sample_count": len(rows),
            "models": {
                name: {
                    "macro_f1":  round(m["__macro_f1__"], 4),
                    "accuracy":  round(m["__accuracy__"], 4),
                    "latency_ms": m["latency_ms"],
                    "per_label": {
                        label: {k: round(v, 4) for k, v in m[label].items()}
                        for label in LABELS
                        if label in m
                    },
                }
                for name, m in results.items()
            },
        }
        save_path = Path(args.score_file).parent / "benchmark_results.json"
        with open(save_path, "w") as f:
            json.dump(save_data, f, indent=2)
        print(f"Results saved → {save_path}", flush=True)


def cmd_compare(args: argparse.Namespace) -> None:
    active = _active_models(args.include_slow)
    if args.models:
        active = {k: v for k, v in active.items() if k in args.models}

    print(f"Fetching up to {args.limit} emails from IMAP …")
    emails = _fetch_imap_sample(args.limit, args.days)
    print(f"Fetched {len(emails)} emails. Loading {len(active)} model(s) …\n")

    adapters = [entry["adapter_instance"] for entry in active.values()]
    model_names = [a.name for a in adapters]

    col = 22
    subj_w = 50
    print(f"{'Subject':<{subj_w}}" + "".join(f"{n:<{col}}" for n in model_names))
    print("-" * (subj_w + col * len(model_names)))

    for row in emails:
        short_subj = row["subject"][:subj_w - 1] if len(row["subject"]) > subj_w else row["subject"]
        line = f"{short_subj:<{subj_w}}"
        for adapter in adapters:
            try:
                label = adapter.classify(row["subject"], row["body"])
            except Exception as exc:
                label = f"ERR:{str(exc)[:8]}"
            line += f"{label:<{col}}"
        print(line, flush=True)

    for adapter in adapters:
        adapter.unload()
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark HuggingFace email classifiers against our 6 labels."
    )
    parser.add_argument("--list-models", action="store_true", help="Show model registry and exit")
    parser.add_argument("--score", action="store_true", help="Score against labeled JSONL")
    parser.add_argument("--compare", action="store_true", help="Visual table on live IMAP emails")
    parser.add_argument("--export-db", action="store_true",
                        help="Export labeled emails from a staging.db → score JSONL")
    parser.add_argument("--score-file", default="data/email_score.jsonl", help="Path to labeled JSONL")
    parser.add_argument("--db", default="data/staging.db", help="Path to staging.db for --export-db")
    parser.add_argument("--limit", type=int, default=20, help="Max emails for --compare")
    parser.add_argument("--days", type=int, default=90, help="Days back for IMAP search")
    parser.add_argument("--include-slow", action="store_true", help="Include non-default heavy models")
    parser.add_argument("--models", nargs="+", help="Override: run only these model names")
    parser.add_argument("--save", action="store_true",
                        help="Save results to data/benchmark_results.json (for the web UI)")

    args = parser.parse_args()

    if args.list_models:
        cmd_list_models(args)
    elif args.score:
        cmd_score(args)
    elif args.compare:
        cmd_compare(args)
    elif args.export_db:
        cmd_export_db(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
