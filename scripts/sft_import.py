"""Avocet — SFT candidate run discovery and JSONL import.

No FastAPI dependency — pure Python file operations.
Used by app/sft.py endpoints and can be run standalone.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CANDIDATES_FILENAME = "sft_candidates.jsonl"


def discover_runs(bench_results_dir: Path) -> list[dict]:
    """Return one entry per run subdirectory that contains sft_candidates.jsonl.

    Sorted newest-first by directory name (directories are named YYYY-MM-DD-HHMMSS
    by the cf-orch benchmark harness, so lexicographic order is chronological).

    Each entry: {run_id, timestamp, candidate_count, sft_path}
    """
    if not bench_results_dir.exists() or not bench_results_dir.is_dir():
        return []
    runs = []
    for subdir in bench_results_dir.iterdir():
        if not subdir.is_dir():
            continue
        sft_path = subdir / _CANDIDATES_FILENAME
        if not sft_path.exists():
            continue
        records = _read_jsonl(sft_path)
        runs.append({
            "run_id": subdir.name,
            "timestamp": subdir.name,
            "candidate_count": len(records),
            "sft_path": sft_path,
        })
    runs.sort(key=lambda r: r["run_id"], reverse=True)
    return runs


def import_run(sft_path: Path, data_dir: Path) -> dict[str, int]:
    """Append records from sft_path into data_dir/sft_candidates.jsonl.

    Deduplicates on the `id` field — records whose id already exists in the
    destination file are skipped silently. Records missing an `id` field are
    also skipped (malformed input from a partial benchmark write).

    Returns {imported: N, skipped: M}.
    """
    dest = data_dir / _CANDIDATES_FILENAME
    existing = _read_jsonl(dest)
    existing_ids = {r["id"] for r in existing if "id" in r}

    new_records: list[dict] = []
    skipped = 0
    for record in _read_jsonl(sft_path):
        if "id" not in record:
            logger.warning("Skipping record missing 'id' field in %s", sft_path)
            continue  # malformed — skip without crashing
        if record["id"] in existing_ids:
            skipped += 1
            continue
        new_records.append(record)
        existing_ids.add(record["id"])

    if new_records:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "a", encoding="utf-8") as fh:
            for r in new_records:
                fh.write(json.dumps(r) + "\n")

    return {"imported": len(new_records), "skipped": skipped}


def _read_jsonl(path: Path) -> list[dict]:
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
