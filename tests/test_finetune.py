"""Tests for finetune_classifier — no model downloads required."""
from __future__ import annotations

import json
import pytest


# ---- Data loading tests ----

def test_load_and_prepare_data_drops_non_canonical_labels(tmp_path):
    """Rows with labels not in LABELS must be silently dropped."""
    from scripts.finetune_classifier import load_and_prepare_data
    from scripts.classifier_adapters import LABELS

    # Two samples per canonical label so they survive the < 2 class-drop rule.
    rows = [
        {"subject": "s1", "body": "b1", "label": "digest"},
        {"subject": "s2", "body": "b2", "label": "digest"},
        {"subject": "s3", "body": "b3", "label": "profile_alert"},  # non-canonical
        {"subject": "s4", "body": "b4", "label": "neutral"},
        {"subject": "s5", "body": "b5", "label": "neutral"},
    ]
    score_file = tmp_path / "email_score.jsonl"
    score_file.write_text("\n".join(json.dumps(r) for r in rows))

    texts, labels = load_and_prepare_data(score_file)
    assert len(texts) == 4
    assert all(l in LABELS for l in labels)


def test_load_and_prepare_data_formats_input_as_sep(tmp_path):
    """Input text must be 'subject [SEP] body[:400]'."""
    # Two samples with the same label so the class survives the < 2 drop rule.
    rows = [
        {"subject": "Hello", "body": "World" * 100, "label": "neutral"},
        {"subject": "Hello2", "body": "World" * 100, "label": "neutral"},
    ]
    score_file = tmp_path / "email_score.jsonl"
    score_file.write_text("\n".join(json.dumps(r) for r in rows))

    from scripts.finetune_classifier import load_and_prepare_data
    texts, labels = load_and_prepare_data(score_file)

    assert texts[0].startswith("Hello [SEP] ")
    parts = texts[0].split(" [SEP] ", 1)
    assert len(parts[1]) == 400, f"Body must be exactly 400 chars, got {len(parts[1])}"


def test_load_and_prepare_data_raises_on_missing_file():
    """FileNotFoundError must be raised with actionable message."""
    from pathlib import Path
    from scripts.finetune_classifier import load_and_prepare_data

    with pytest.raises(FileNotFoundError, match="email_score.jsonl"):
        load_and_prepare_data(Path("/nonexistent/email_score.jsonl"))


def test_load_and_prepare_data_drops_class_with_fewer_than_2_samples(tmp_path, capsys):
    """Classes with < 2 total samples must be dropped with a warning."""
    from scripts.finetune_classifier import load_and_prepare_data

    rows = [
        {"subject": "s1", "body": "b", "label": "digest"},
        {"subject": "s2", "body": "b", "label": "digest"},
        {"subject": "s3", "body": "b", "label": "new_lead"},  # only 1 sample — drop
    ]
    score_file = tmp_path / "email_score.jsonl"
    score_file.write_text("\n".join(json.dumps(r) for r in rows))

    texts, labels = load_and_prepare_data(score_file)
    captured = capsys.readouterr()

    assert "new_lead" not in labels
    assert "new_lead" in captured.out  # warning printed


# ---- Class weights tests ----

def test_compute_class_weights_returns_tensor_for_each_class():
    """compute_class_weights must return a float tensor of length n_classes."""
    import torch
    from scripts.finetune_classifier import compute_class_weights

    label_ids = [0, 0, 0, 1, 1, 2]  # 3 classes, imbalanced
    weights = compute_class_weights(label_ids, n_classes=3)

    assert isinstance(weights, torch.Tensor)
    assert weights.shape == (3,)
    assert all(w > 0 for w in weights)


def test_compute_class_weights_upweights_minority():
    """Minority classes must receive higher weight than majority classes."""
    from scripts.finetune_classifier import compute_class_weights

    # Class 0: 10 samples, Class 1: 2 samples
    label_ids = [0] * 10 + [1] * 2
    weights = compute_class_weights(label_ids, n_classes=2)

    assert weights[1] > weights[0]


# ---- compute_metrics_for_trainer tests ----

def test_compute_metrics_for_trainer_returns_macro_f1_key():
    """Must return a dict with 'macro_f1' key."""
    import numpy as np
    from scripts.finetune_classifier import compute_metrics_for_trainer
    from transformers import EvalPrediction

    logits = np.array([[2.0, 0.1], [0.1, 2.0], [2.0, 0.1]])
    labels = np.array([0, 1, 0])
    pred = EvalPrediction(predictions=logits, label_ids=labels)

    result = compute_metrics_for_trainer(pred)
    assert "macro_f1" in result
    assert result["macro_f1"] == pytest.approx(1.0)


def test_compute_metrics_for_trainer_returns_accuracy_key():
    """Must also return 'accuracy' key."""
    import numpy as np
    from scripts.finetune_classifier import compute_metrics_for_trainer
    from transformers import EvalPrediction

    logits = np.array([[2.0, 0.1], [0.1, 2.0]])
    labels = np.array([0, 1])
    pred = EvalPrediction(predictions=logits, label_ids=labels)

    result = compute_metrics_for_trainer(pred)
    assert "accuracy" in result
    assert result["accuracy"] == pytest.approx(1.0)


# ---- WeightedTrainer tests ----

def test_weighted_trainer_compute_loss_returns_scalar():
    """compute_loss must return a scalar tensor when return_outputs=False."""
    import torch
    from unittest.mock import MagicMock
    from scripts.finetune_classifier import WeightedTrainer

    n_classes = 3
    batch = 4
    logits = torch.randn(batch, n_classes)

    mock_outputs = MagicMock()
    mock_outputs.logits = logits
    mock_model = MagicMock(return_value=mock_outputs)

    trainer = WeightedTrainer.__new__(WeightedTrainer)
    trainer.class_weights = torch.ones(n_classes)

    inputs = {
        "input_ids": torch.zeros(batch, 10, dtype=torch.long),
        "labels": torch.randint(0, n_classes, (batch,)),
    }

    loss = trainer.compute_loss(mock_model, inputs, return_outputs=False)
    assert isinstance(loss, torch.Tensor)
    assert loss.ndim == 0  # scalar


def test_weighted_trainer_compute_loss_accepts_kwargs():
    """compute_loss must not raise TypeError when called with num_items_in_batch kwarg."""
    import torch
    from unittest.mock import MagicMock
    from scripts.finetune_classifier import WeightedTrainer

    n_classes = 3
    batch = 2
    logits = torch.randn(batch, n_classes)

    mock_outputs = MagicMock()
    mock_outputs.logits = logits
    mock_model = MagicMock(return_value=mock_outputs)

    trainer = WeightedTrainer.__new__(WeightedTrainer)
    trainer.class_weights = torch.ones(n_classes)

    inputs = {
        "input_ids": torch.zeros(batch, 5, dtype=torch.long),
        "labels": torch.randint(0, n_classes, (batch,)),
    }

    loss = trainer.compute_loss(mock_model, inputs, return_outputs=False,
                                num_items_in_batch=batch)
    assert isinstance(loss, torch.Tensor)


def test_weighted_trainer_weighted_loss_differs_from_unweighted():
    """Weighted loss must differ from uniform-weight loss for imbalanced inputs."""
    import torch
    from unittest.mock import MagicMock
    from scripts.finetune_classifier import WeightedTrainer

    n_classes = 2
    batch = 4
    # Mixed labels: 3× class-0, 1× class-1.
    # Asymmetric logits (class-0 samples predicted well, class-1 predicted poorly)
    # ensure per-class CE values differ, so re-weighting changes the weighted mean.
    labels = torch.tensor([0, 0, 0, 1], dtype=torch.long)
    logits = torch.tensor([[3.0, -1.0], [3.0, -1.0], [3.0, -1.0], [0.5, 0.5]])

    mock_outputs = MagicMock()
    mock_outputs.logits = logits

    trainer_uniform = WeightedTrainer.__new__(WeightedTrainer)
    trainer_uniform.class_weights = torch.ones(n_classes)
    inputs_uniform = {"input_ids": torch.zeros(batch, 5, dtype=torch.long), "labels": labels.clone()}
    loss_uniform = trainer_uniform.compute_loss(MagicMock(return_value=mock_outputs),
                                                inputs_uniform)

    trainer_weighted = WeightedTrainer.__new__(WeightedTrainer)
    trainer_weighted.class_weights = torch.tensor([0.1, 10.0])
    inputs_weighted = {"input_ids": torch.zeros(batch, 5, dtype=torch.long), "labels": labels.clone()}

    mock_outputs2 = MagicMock()
    mock_outputs2.logits = logits.clone()
    loss_weighted = trainer_weighted.compute_loss(MagicMock(return_value=mock_outputs2),
                                                  inputs_weighted)

    assert not torch.isclose(loss_uniform, loss_weighted)


def test_weighted_trainer_compute_loss_returns_outputs_when_requested():
    """compute_loss with return_outputs=True must return (loss, outputs) tuple."""
    import torch
    from unittest.mock import MagicMock
    from scripts.finetune_classifier import WeightedTrainer

    n_classes = 3
    batch = 2
    logits = torch.randn(batch, n_classes)

    mock_outputs = MagicMock()
    mock_outputs.logits = logits
    mock_model = MagicMock(return_value=mock_outputs)

    trainer = WeightedTrainer.__new__(WeightedTrainer)
    trainer.class_weights = torch.ones(n_classes)

    inputs = {
        "input_ids": torch.zeros(batch, 5, dtype=torch.long),
        "labels": torch.randint(0, n_classes, (batch,)),
    }

    result = trainer.compute_loss(mock_model, inputs, return_outputs=True)
    assert isinstance(result, tuple)
    loss, outputs = result
    assert isinstance(loss, torch.Tensor)
