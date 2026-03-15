"""Tests for benchmark_classifier — no model downloads required."""
import pytest


def test_registry_has_thirteen_models():
    from scripts.benchmark_classifier import MODEL_REGISTRY
    assert len(MODEL_REGISTRY) == 13


def test_registry_default_count():
    from scripts.benchmark_classifier import MODEL_REGISTRY
    defaults = [k for k, v in MODEL_REGISTRY.items() if v["default"]]
    assert len(defaults) == 7


def test_registry_entries_have_required_keys():
    from scripts.benchmark_classifier import MODEL_REGISTRY
    from scripts.classifier_adapters import ClassifierAdapter
    for name, entry in MODEL_REGISTRY.items():
        assert "adapter" in entry, f"{name} missing 'adapter'"
        assert "model_id" in entry, f"{name} missing 'model_id'"
        assert "params" in entry, f"{name} missing 'params'"
        assert "default" in entry, f"{name} missing 'default'"
        assert issubclass(entry["adapter"], ClassifierAdapter), \
            f"{name} adapter must be a ClassifierAdapter subclass"


def test_load_scoring_jsonl(tmp_path):
    from scripts.benchmark_classifier import load_scoring_jsonl
    import json
    f = tmp_path / "score.jsonl"
    rows = [
        {"subject": "Hi", "body": "Body text", "label": "neutral"},
        {"subject": "Interview", "body": "Schedule a call", "label": "interview_scheduled"},
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows))
    result = load_scoring_jsonl(str(f))
    assert len(result) == 2
    assert result[0]["label"] == "neutral"


def test_load_scoring_jsonl_missing_file():
    from scripts.benchmark_classifier import load_scoring_jsonl
    with pytest.raises(FileNotFoundError):
        load_scoring_jsonl("/nonexistent/path.jsonl")


def test_run_scoring_with_mock_adapters(tmp_path):
    """run_scoring() returns per-model metrics using mock adapters."""
    import json
    from unittest.mock import MagicMock
    from scripts.benchmark_classifier import run_scoring

    score_file = tmp_path / "score.jsonl"
    rows = [
        {"subject": "Interview", "body": "Let's schedule", "label": "interview_scheduled"},
        {"subject": "Sorry", "body": "We went with others", "label": "rejected"},
        {"subject": "Offer", "body": "We are pleased", "label": "offer_received"},
    ]
    score_file.write_text("\n".join(json.dumps(r) for r in rows))

    perfect = MagicMock()
    perfect.name = "perfect"
    perfect.classify.side_effect = lambda s, b: (
        "interview_scheduled" if "Interview" in s else
        "rejected" if "Sorry" in s else "offer_received"
    )

    bad = MagicMock()
    bad.name = "bad"
    bad.classify.return_value = "neutral"

    results = run_scoring([perfect, bad], str(score_file))

    assert results["perfect"]["__accuracy__"] == pytest.approx(1.0)
    assert results["bad"]["__accuracy__"] == pytest.approx(0.0)
    assert "latency_ms" in results["perfect"]


def test_run_scoring_handles_classify_error(tmp_path):
    """run_scoring() falls back to 'neutral' on exception and continues."""
    import json
    from unittest.mock import MagicMock
    from scripts.benchmark_classifier import run_scoring

    score_file = tmp_path / "score.jsonl"
    score_file.write_text(json.dumps({"subject": "Hi", "body": "Body", "label": "neutral"}))

    broken = MagicMock()
    broken.name = "broken"
    broken.classify.side_effect = RuntimeError("model crashed")

    results = run_scoring([broken], str(score_file))
    assert "broken" in results


# ---- Auto-discovery tests ----

def test_discover_finetuned_models_finds_training_info_files(tmp_path):
    """discover_finetuned_models() must return one entry per training_info.json found."""
    import json
    from scripts.benchmark_classifier import discover_finetuned_models

    # Create two fake model directories
    for name in ("avocet-deberta-small", "avocet-bge-m3"):
        model_dir = tmp_path / name
        model_dir.mkdir()
        info = {
            "name": name,
            "base_model_id": "cross-encoder/nli-deberta-v3-small",
            "timestamp": "2026-03-15T12:00:00Z",
            "val_macro_f1": 0.72,
            "val_accuracy": 0.80,
            "sample_count": 401,
        }
        (model_dir / "training_info.json").write_text(json.dumps(info))

    results = discover_finetuned_models(tmp_path)
    assert len(results) == 2
    names = {r["name"] for r in results}
    assert "avocet-deberta-small" in names
    assert "avocet-bge-m3" in names


def test_discover_finetuned_models_returns_empty_when_no_models_dir():
    """discover_finetuned_models() must return [] silently if models/ doesn't exist."""
    from pathlib import Path
    from scripts.benchmark_classifier import discover_finetuned_models

    results = discover_finetuned_models(Path("/nonexistent/path/models"))
    assert results == []


def test_discover_finetuned_models_skips_dirs_without_training_info(tmp_path):
    """Subdirs without training_info.json are silently skipped."""
    from scripts.benchmark_classifier import discover_finetuned_models

    # A dir WITHOUT training_info.json
    (tmp_path / "some-other-dir").mkdir()

    results = discover_finetuned_models(tmp_path)
    assert results == []


def test_active_models_includes_discovered_finetuned(tmp_path):
    """The active models dict must include FineTunedAdapter entries for discovered models."""
    import json
    from unittest.mock import patch
    from scripts.benchmark_classifier import _active_models
    from scripts.classifier_adapters import FineTunedAdapter

    model_dir = tmp_path / "avocet-deberta-small"
    model_dir.mkdir()
    (model_dir / "training_info.json").write_text(json.dumps({
        "name": "avocet-deberta-small",
        "base_model_id": "cross-encoder/nli-deberta-v3-small",
        "val_macro_f1": 0.72,
        "sample_count": 401,
    }))

    with patch("scripts.benchmark_classifier._MODELS_DIR", tmp_path):
        models = _active_models(include_slow=False)

    assert "avocet-deberta-small" in models
    assert isinstance(models["avocet-deberta-small"]["adapter_instance"], FineTunedAdapter)
