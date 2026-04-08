"""Unit tests for scripts/sft_import.py — run discovery and JSONL deduplication."""
import json
import pytest
from pathlib import Path


def _write_candidates(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _make_record(id: str, run_id: str = "run1") -> dict:
    return {
        "id": id, "source": "cf-orch-benchmark",
        "benchmark_run_id": run_id, "timestamp": "2026-04-07T10:00:00Z",
        "status": "needs_review", "prompt_messages": [],
        "model_response": "bad", "corrected_response": None,
        "quality_score": 0.3, "failure_reason": "missing patterns",
        "task_id": "code-fn", "task_type": "code", "task_name": "Code: fn",
        "model_id": "Qwen/Qwen2.5-3B", "model_name": "Qwen2.5-3B",
        "node_id": "heimdall", "gpu_id": 0, "tokens_per_sec": 38.4,
    }


def test_discover_runs_empty_when_dir_missing(tmp_path):
    from scripts.sft_import import discover_runs
    result = discover_runs(tmp_path / "nonexistent")
    assert result == []


def test_discover_runs_returns_runs(tmp_path):
    from scripts.sft_import import discover_runs
    run_dir = tmp_path / "2026-04-07-143022"
    _write_candidates(run_dir / "sft_candidates.jsonl", [_make_record("a"), _make_record("b")])
    result = discover_runs(tmp_path)
    assert len(result) == 1
    assert result[0]["run_id"] == "2026-04-07-143022"
    assert result[0]["candidate_count"] == 2
    assert "sft_path" in result[0]


def test_discover_runs_skips_dirs_without_sft_file(tmp_path):
    from scripts.sft_import import discover_runs
    (tmp_path / "2026-04-07-no-sft").mkdir()
    result = discover_runs(tmp_path)
    assert result == []


def test_discover_runs_sorted_newest_first(tmp_path):
    from scripts.sft_import import discover_runs
    for name in ["2026-04-05-120000", "2026-04-07-143022", "2026-04-06-090000"]:
        run_dir = tmp_path / name
        _write_candidates(run_dir / "sft_candidates.jsonl", [_make_record("x")])
    result = discover_runs(tmp_path)
    assert [r["run_id"] for r in result] == [
        "2026-04-07-143022", "2026-04-06-090000", "2026-04-05-120000"
    ]


def test_import_run_imports_new_records(tmp_path):
    from scripts.sft_import import import_run
    sft_path = tmp_path / "run1" / "sft_candidates.jsonl"
    _write_candidates(sft_path, [_make_record("a"), _make_record("b")])
    result = import_run(sft_path, tmp_path)
    assert result == {"imported": 2, "skipped": 0}
    dest = tmp_path / "sft_candidates.jsonl"
    lines = [json.loads(l) for l in dest.read_text().splitlines() if l.strip()]
    assert len(lines) == 2


def test_import_run_deduplicates_on_id(tmp_path):
    from scripts.sft_import import import_run
    sft_path = tmp_path / "run1" / "sft_candidates.jsonl"
    _write_candidates(sft_path, [_make_record("a"), _make_record("b")])
    import_run(sft_path, tmp_path)
    result = import_run(sft_path, tmp_path)  # second import
    assert result == {"imported": 0, "skipped": 2}
    dest = tmp_path / "sft_candidates.jsonl"
    lines = [l for l in dest.read_text().splitlines() if l.strip()]
    assert len(lines) == 2  # no duplicates


def test_import_run_skips_records_missing_id(tmp_path):
    from scripts.sft_import import import_run
    sft_path = tmp_path / "run1" / "sft_candidates.jsonl"
    bad = {"source": "cf-orch-benchmark", "status": "needs_review"}  # no id
    _write_candidates(sft_path, [bad, _make_record("a")])
    result = import_run(sft_path, tmp_path)
    assert result == {"imported": 1, "skipped": 0}
