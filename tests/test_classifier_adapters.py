"""Tests for classifier_adapters — no model downloads required."""
import pytest


def test_labels_constant_has_ten_items():
    from scripts.classifier_adapters import LABELS
    assert len(LABELS) == 10
    assert "interview_scheduled" in LABELS
    assert "neutral" in LABELS
    assert "event_rescheduled" in LABELS
    assert "digest" in LABELS
    assert "new_lead" in LABELS
    assert "hired" in LABELS
    assert "unrelated" not in LABELS


def test_compute_metrics_perfect_predictions():
    from scripts.classifier_adapters import compute_metrics, LABELS
    gold  = ["rejected", "interview_scheduled", "neutral"]
    preds = ["rejected", "interview_scheduled", "neutral"]
    m = compute_metrics(preds, gold, LABELS)
    assert m["rejected"]["f1"] == pytest.approx(1.0)
    assert m["__accuracy__"] == pytest.approx(1.0)
    assert m["__macro_f1__"] == pytest.approx(1.0)


def test_compute_metrics_all_wrong():
    from scripts.classifier_adapters import compute_metrics, LABELS
    gold  = ["rejected",  "rejected"]
    preds = ["neutral",   "interview_scheduled"]
    m = compute_metrics(preds, gold, LABELS)
    assert m["rejected"]["recall"] == pytest.approx(0.0)
    assert m["__accuracy__"] == pytest.approx(0.0)


def test_compute_metrics_partial():
    from scripts.classifier_adapters import compute_metrics, LABELS
    gold  = ["rejected", "neutral", "rejected"]
    preds = ["rejected", "neutral", "interview_scheduled"]
    m = compute_metrics(preds, gold, LABELS)
    assert m["rejected"]["precision"] == pytest.approx(1.0)
    assert m["rejected"]["recall"]    == pytest.approx(0.5)
    assert m["neutral"]["f1"]         == pytest.approx(1.0)
    assert m["__accuracy__"]          == pytest.approx(2 / 3)


def test_compute_metrics_empty():
    from scripts.classifier_adapters import compute_metrics, LABELS
    m = compute_metrics([], [], LABELS)
    assert m["__accuracy__"] == pytest.approx(0.0)


def test_classifier_adapter_is_abstract():
    from scripts.classifier_adapters import ClassifierAdapter
    with pytest.raises(TypeError):
        ClassifierAdapter()


# ---- ZeroShotAdapter tests ----

def test_zeroshot_adapter_classify_mocked():
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import ZeroShotAdapter

    # Two-level mock: factory call returns pipeline instance; instance call returns inference result.
    mock_pipe_factory = MagicMock()
    mock_pipe_factory.return_value = MagicMock(return_value={
        "labels": ["rejected", "neutral", "interview_scheduled"],
        "scores": [0.85, 0.10, 0.05],
    })

    with patch("scripts.classifier_adapters.pipeline", mock_pipe_factory):
        adapter = ZeroShotAdapter("test-zs", "some/model")
        adapter.load()
        result = adapter.classify("We went with another candidate", "Thank you for applying.")

    assert result == "rejected"
    # Factory was called with the correct task type
    assert mock_pipe_factory.call_args[0][0] == "zero-shot-classification"
    # Pipeline instance was called with the email text
    assert "We went with another candidate" in mock_pipe_factory.return_value.call_args[0][0]


def test_zeroshot_adapter_unload_clears_pipeline():
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import ZeroShotAdapter

    with patch("scripts.classifier_adapters.pipeline", MagicMock()):
        adapter = ZeroShotAdapter("test-zs", "some/model")
        adapter.load()
        assert adapter._pipeline is not None
        adapter.unload()
        assert adapter._pipeline is None


def test_zeroshot_adapter_lazy_loads():
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import ZeroShotAdapter

    mock_pipe_factory = MagicMock()
    mock_pipe_factory.return_value = MagicMock(return_value={
        "labels": ["neutral"], "scores": [1.0]
    })

    with patch("scripts.classifier_adapters.pipeline", mock_pipe_factory):
        adapter = ZeroShotAdapter("test-zs", "some/model")
        adapter.classify("subject", "body")

    mock_pipe_factory.assert_called_once()


# ---- GLiClassAdapter tests ----

def test_gliclass_adapter_classify_mocked():
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import GLiClassAdapter

    mock_pipeline_instance = MagicMock()
    mock_pipeline_instance.return_value = [[
        {"label": "interview_scheduled", "score": 0.91},
        {"label": "neutral", "score": 0.05},
        {"label": "rejected", "score": 0.04},
    ]]

    with patch("scripts.classifier_adapters.GLiClassModel") as _mc, \
         patch("scripts.classifier_adapters.AutoTokenizer") as _mt, \
         patch("scripts.classifier_adapters.ZeroShotClassificationPipeline",
               return_value=mock_pipeline_instance):
        adapter = GLiClassAdapter("test-gli", "some/gliclass-model")
        adapter.load()
        result = adapter.classify("Interview invitation", "Let's schedule a call.")

    assert result == "interview_scheduled"


def test_gliclass_adapter_returns_highest_score():
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import GLiClassAdapter

    mock_pipeline_instance = MagicMock()
    mock_pipeline_instance.return_value = [[
        {"label": "neutral", "score": 0.02},
        {"label": "offer_received", "score": 0.88},
        {"label": "rejected", "score": 0.10},
    ]]

    with patch("scripts.classifier_adapters.GLiClassModel"), \
         patch("scripts.classifier_adapters.AutoTokenizer"), \
         patch("scripts.classifier_adapters.ZeroShotClassificationPipeline",
               return_value=mock_pipeline_instance):
        adapter = GLiClassAdapter("test-gli", "some/model")
        adapter.load()
        result = adapter.classify("Offer letter enclosed", "Dear Meghan, we are pleased to offer...")

    assert result == "offer_received"


# ---- RerankerAdapter tests ----

def test_reranker_adapter_picks_highest_score():
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import RerankerAdapter, LABELS

    mock_reranker = MagicMock()
    mock_reranker.compute_score.return_value = [0.1, 0.05, 0.85, 0.05, 0.02, 0.03]

    with patch("scripts.classifier_adapters.FlagReranker", return_value=mock_reranker):
        adapter = RerankerAdapter("test-rr", "BAAI/bge-reranker-v2-m3")
        adapter.load()
        result = adapter.classify(
            "We regret to inform you",
            "After careful consideration we are moving forward with other candidates.",
        )

    assert result == "rejected"
    pairs = mock_reranker.compute_score.call_args[0][0]
    assert len(pairs) == len(LABELS)


def test_reranker_adapter_descriptions_cover_all_labels():
    from scripts.classifier_adapters import LABEL_DESCRIPTIONS, LABELS
    assert set(LABEL_DESCRIPTIONS.keys()) == set(LABELS)


# ---- FineTunedAdapter tests ----

def test_finetuned_adapter_classify_calls_pipeline_with_sep_format(tmp_path):
    """classify() must format input as 'subject [SEP] body[:400]' — not the zero-shot format."""
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import FineTunedAdapter

    mock_result = [{"label": "digest", "score": 0.95}]
    mock_pipe_instance = MagicMock(return_value=mock_result)
    mock_pipe_factory = MagicMock(return_value=mock_pipe_instance)

    adapter = FineTunedAdapter("avocet-deberta-small", str(tmp_path))
    with patch("scripts.classifier_adapters.pipeline", mock_pipe_factory):
        result = adapter.classify("Test subject", "Test body")

    assert result == "digest"
    call_args = mock_pipe_instance.call_args[0][0]
    assert "[SEP]" in call_args
    assert "Test subject" in call_args
    assert "Test body" in call_args


def test_finetuned_adapter_truncates_body_to_400():
    """Body must be truncated to 400 chars in the [SEP] format."""
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import FineTunedAdapter, LABELS

    long_body = "x" * 800
    mock_result = [{"label": "neutral", "score": 0.9}]
    mock_pipe_instance = MagicMock(return_value=mock_result)
    mock_pipe_factory = MagicMock(return_value=mock_pipe_instance)

    adapter = FineTunedAdapter("avocet-deberta-small", "/fake/path")
    with patch("scripts.classifier_adapters.pipeline", mock_pipe_factory):
        adapter.classify("Subject", long_body)

    call_text = mock_pipe_instance.call_args[0][0]
    parts = call_text.split(" [SEP] ", 1)
    assert len(parts) == 2, "Input must contain ' [SEP] ' separator"
    assert len(parts[1]) == 400, f"Body must be exactly 400 chars, got {len(parts[1])}"


def test_finetuned_adapter_returns_label_string():
    """classify() must return a plain string, not a dict."""
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import FineTunedAdapter

    mock_result = [{"label": "interview_scheduled", "score": 0.87}]
    mock_pipe_instance = MagicMock(return_value=mock_result)
    mock_pipe_factory = MagicMock(return_value=mock_pipe_instance)

    adapter = FineTunedAdapter("avocet-deberta-small", "/fake/path")
    with patch("scripts.classifier_adapters.pipeline", mock_pipe_factory):
        result = adapter.classify("S", "B")

    assert isinstance(result, str)
    assert result == "interview_scheduled"


def test_finetuned_adapter_lazy_loads_pipeline():
    """Pipeline factory must not be called until classify() is first called."""
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import FineTunedAdapter

    mock_pipe_factory = MagicMock(return_value=MagicMock(return_value=[{"label": "neutral", "score": 0.9}]))

    with patch("scripts.classifier_adapters.pipeline", mock_pipe_factory):
        adapter = FineTunedAdapter("avocet-deberta-small", "/fake/path")
        assert not mock_pipe_factory.called
        adapter.classify("s", "b")
        assert mock_pipe_factory.called


def test_finetuned_adapter_unload_clears_pipeline():
    """unload() must set _pipeline to None so memory is released."""
    from unittest.mock import MagicMock, patch
    from scripts.classifier_adapters import FineTunedAdapter

    mock_pipe_factory = MagicMock(return_value=MagicMock(return_value=[{"label": "neutral", "score": 0.9}]))

    with patch("scripts.classifier_adapters.pipeline", mock_pipe_factory):
        adapter = FineTunedAdapter("avocet-deberta-small", "/fake/path")
        adapter.classify("s", "b")
        assert adapter._pipeline is not None
        adapter.unload()
        assert adapter._pipeline is None

# ---- _cosine() tests ----

def test_cosine_identical_unit_vectors():
    import math
    from scripts.classifier_adapters import _cosine
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    from scripts.classifier_adapters import _cosine
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_known_value():
    import math
    from scripts.classifier_adapters import _cosine
    # [1,0] vs [1/sqrt(2), 1/sqrt(2)] → dot = 1/sqrt(2), both norms = 1 → 1/sqrt(2)
    v = [1.0 / math.sqrt(2), 1.0 / math.sqrt(2)]
    assert _cosine([1.0, 0.0], v) == pytest.approx(1.0 / math.sqrt(2))


def test_cosine_zero_vector_returns_zero():
    from scripts.classifier_adapters import _cosine
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


# ---- DEFAULT_EXEMPLARS tests ----

def test_default_exemplars_covers_all_labels():
    from scripts.classifier_adapters import DEFAULT_EXEMPLARS, LABELS
    for label in LABELS:
        assert label in DEFAULT_EXEMPLARS, f"DEFAULT_EXEMPLARS missing label: {label}"
        assert len(DEFAULT_EXEMPLARS[label]) >= 4, f"{label} needs >= 4 exemplars for k=3 voting"


def test_default_exemplars_sparse_labels_have_at_least_four():
    from scripts.classifier_adapters import DEFAULT_EXEMPLARS
    # These labels have very few real examples; need >= 4 so k=3 vote is meaningful
    for label in ("hired", "survey_received", "event_rescheduled"):
        assert len(DEFAULT_EXEMPLARS[label]) >= 4, (
            f"{label} needs >= 4 exemplars for k=3 voting to work reliably"
        )

def test_default_exemplars_strings_are_formatted_correctly():
    from scripts.classifier_adapters import DEFAULT_EXEMPLARS
    for label, texts in DEFAULT_EXEMPLARS.items():
        for text in texts:
            assert text.startswith("Subject: "), (
                f"{label!r} exemplar missing 'Subject: ' prefix: {text[:50]!r}"
            )
            assert "\n\n" in text, (
                f"{label!r} exemplar missing double-newline separator: {text[:50]!r}"
            )
