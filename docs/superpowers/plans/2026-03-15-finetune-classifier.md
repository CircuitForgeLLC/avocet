# Fine-tune Email Classifier Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fine-tune `deberta-small` and `bge-m3` on the labeled dataset, surface trained models in the benchmark harness, and expose a UI-triggerable training workflow with SSE streaming logs.

**Architecture:** A new CLI script (`scripts/finetune_classifier.py`) handles data prep, weighted training, and checkpoint saving. A new `FineTunedAdapter` in `classifier_adapters.py` loads saved checkpoints for inference. `benchmark_classifier.py` auto-discovers these adapters at startup via `training_info.json` files. Two GET endpoints in `api.py` expose status and streaming run. `BenchmarkView.vue` adds a badge row and collapsible fine-tune section.

**Tech Stack:** transformers 4.57.3, torch 2.10.0, accelerate 1.12.0, scikit-learn (new), FastAPI SSE, Vue 3 + EventSource

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `environment.yml` | Modify | Add `scikit-learn` dependency |
| `scripts/classifier_adapters.py` | Modify | Add `FineTunedAdapter` class |
| `scripts/benchmark_classifier.py` | Modify | Add `_MODELS_DIR`, `discover_finetuned_models()`, merge into model registry at startup |
| `scripts/finetune_classifier.py` | Create | Full training pipeline: data prep, class weights, `WeightedTrainer`, CLI |
| `app/api.py` | Modify | Add `GET /api/finetune/status` and `GET /api/finetune/run` |
| `web/src/views/BenchmarkView.vue` | Modify | Add trained models badge row + collapsible fine-tune section |
| `tests/test_classifier_adapters.py` | Modify | Add `FineTunedAdapter` unit tests |
| `tests/test_benchmark_classifier.py` | Modify | Add auto-discovery unit tests |
| `tests/test_finetune.py` | Create | Unit tests for data pipeline, `WeightedTrainer`, `compute_metrics_for_trainer` |
| `tests/test_api.py` | Modify | Add tests for `/api/finetune/status` and `/api/finetune/run` |

---

## Chunk 1: Foundation — FineTunedAdapter + Auto-discovery

### Task 1: Add scikit-learn to environment.yml

**Files:**
- Modify: `environment.yml`

- [ ] **Step 1: Add scikit-learn**

Edit `environment.yml` — add `scikit-learn>=1.4` in the pip section after `accelerate`:

```yaml
    - scikit-learn>=1.4
```

- [ ] **Step 2: Verify environment.yml is valid YAML**

```bash
python -c "import yaml; yaml.safe_load(open('environment.yml'))" && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add environment.yml
git commit -m "chore(avocet): add scikit-learn to classifier env"
```

---

### Task 2: FineTunedAdapter — write failing tests

**Files:**
- Modify: `tests/test_classifier_adapters.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classifier_adapters.py`:

```python

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
    # "Subject [SEP] " prefix + 400 body chars = 414 chars max
    assert len(call_text) <= 420


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_classifier_adapters.py -k "finetuned" -v
```

Expected: `ImportError` or `AttributeError` — `FineTunedAdapter` not yet defined.

---

### Task 3: FineTunedAdapter — implement

**Files:**
- Modify: `scripts/classifier_adapters.py`

- [ ] **Step 1: Add FineTunedAdapter to `__all__`**

In `scripts/classifier_adapters.py`, add `"FineTunedAdapter"` to `__all__`.

- [ ] **Step 2: Implement FineTunedAdapter**

Append after `RerankerAdapter`:

```python
class FineTunedAdapter(ClassifierAdapter):
    """Loads a fine-tuned checkpoint from a local models/ directory.

    Uses pipeline("text-classification") for a single forward pass.
    Input format: 'subject [SEP] body[:400]' — must match training format exactly.
    Expected inference speed: ~10–20ms/email vs 111–338ms for zero-shot.
    """

    def __init__(self, name: str, model_dir: str) -> None:
        self._name = name
        self._model_dir = model_dir
        self._pipeline: Any = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return self._model_dir

    def load(self) -> None:
        import scripts.classifier_adapters as _mod  # noqa: PLC0415
        _pipe_fn = _mod.pipeline
        if _pipe_fn is None:
            raise ImportError("transformers not installed")
        self._pipeline = _pipe_fn("text-classification", model=self._model_dir)

    def unload(self) -> None:
        self._pipeline = None

    def classify(self, subject: str, body: str) -> str:
        if self._pipeline is None:
            self.load()
        text = f"{subject} [SEP] {body[:400]}"
        result = self._pipeline(text)
        return result[0]["label"]
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_classifier_adapters.py -k "finetuned" -v
```

Expected: 5 tests PASS.

- [ ] **Step 4: Run full adapter test suite to verify no regressions**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_classifier_adapters.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/classifier_adapters.py tests/test_classifier_adapters.py
git commit -m "feat(avocet): add FineTunedAdapter for local checkpoint inference"
```

---

### Task 4: Auto-discovery in benchmark_classifier.py — write failing tests

**Files:**
- Modify: `tests/test_benchmark_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_benchmark_classifier.py`:

```python

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_benchmark_classifier.py -k "discover or active_models" -v
```

Expected: `ImportError` — `discover_finetuned_models` and `_MODELS_DIR` not yet defined.

---

### Task 5: Auto-discovery — implement in benchmark_classifier.py

**Files:**
- Modify: `scripts/benchmark_classifier.py`

- [ ] **Step 1: Add imports and _MODELS_DIR**

Near the top of `scripts/benchmark_classifier.py`, after the existing imports, add:

```python
from scripts.classifier_adapters import FineTunedAdapter
```

And define `_MODELS_DIR` (after `_ROOT` is defined — find where `_ROOT = Path(__file__).parent.parent` is, or add it):

```python
_ROOT = Path(__file__).parent.parent
_MODELS_DIR = _ROOT / "models"
```

(If `_ROOT` already exists in the file, only add `_MODELS_DIR`.)

- [ ] **Step 2: Add discover_finetuned_models()**

Add after the `MODEL_REGISTRY` dict:

```python
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
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info["model_dir"] = str(sub)
        found.append(info)
    return found
```

- [ ] **Step 3: Add _active_models() function**

Add after `discover_finetuned_models()`:

```python
def _active_models(include_slow: bool = False) -> dict[str, dict]:
    """Return the active model registry, merged with any discovered fine-tuned models."""
    active = {
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_benchmark_classifier.py -k "discover or active_models" -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Run full benchmark test suite**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_benchmark_classifier.py -v
```

Expected: All tests PASS. (Existing tests that construct adapters directly from `MODEL_REGISTRY` still work because we only added new functions.)

- [ ] **Step 6: Commit**

```bash
git add scripts/benchmark_classifier.py tests/test_benchmark_classifier.py
git commit -m "feat(avocet): auto-discover fine-tuned models in benchmark harness"
```

---

## Chunk 2: Training Script — finetune_classifier.py

### Task 6: Data loading and class weights — write failing tests

**Files:**
- Create: `tests/test_finetune.py`

- [ ] **Step 1: Create test file with data pipeline tests**

Create `tests/test_finetune.py`:

```python
"""Tests for finetune_classifier — no model downloads required."""
from __future__ import annotations

import json
import pytest


# ---- Data loading tests ----

def test_load_and_prepare_data_drops_non_canonical_labels(tmp_path):
    """Rows with labels not in LABELS must be silently dropped."""
    from scripts.finetune_classifier import load_and_prepare_data
    from scripts.classifier_adapters import LABELS

    rows = [
        {"subject": "s1", "body": "b1", "label": "digest"},
        {"subject": "s2", "body": "b2", "label": "profile_alert"},  # non-canonical
        {"subject": "s3", "body": "b3", "label": "neutral"},
    ]
    score_file = tmp_path / "email_score.jsonl"
    score_file.write_text("\n".join(json.dumps(r) for r in rows))

    texts, labels = load_and_prepare_data(score_file)
    assert len(texts) == 2
    assert all(l in LABELS for l in labels)


def test_load_and_prepare_data_formats_input_as_sep():
    """Input text must be 'subject [SEP] body[:400]'."""
    import json
    from pathlib import Path
    from scripts.finetune_classifier import load_and_prepare_data

    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"subject": "Hello", "body": "World" * 100, "label": "neutral"}) + "\n")
        fname = f.name

    try:
        texts, labels = load_and_prepare_data(Path(fname))
    finally:
        os.unlink(fname)

    assert texts[0].startswith("Hello [SEP] ")
    assert len(texts[0]) <= len("Hello [SEP] ") + 400 + 5  # small buffer for truncation


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_finetune.py -k "load_and_prepare or class_weights or compute_metrics_for_trainer" -v
```

Expected: `ModuleNotFoundError` — `scripts.finetune_classifier` not yet created.

---

### Task 7: Implement data loading and class weights in finetune_classifier.py

**Files:**
- Create: `scripts/finetune_classifier.py`

- [ ] **Step 1: Create finetune_classifier.py with data loading + class weights**

Create `scripts/finetune_classifier.py`:

```python
"""Fine-tune email classifiers on the labeled dataset.

CLI entry point. All prints use flush=True so stdout is SSE-streamable.

Usage:
    python scripts/finetune_classifier.py --model deberta-small [--epochs 5]

Supported --model values: deberta-small, bge-m3
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, accuracy_score
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    EvalPrediction,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback,
)

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.classifier_adapters import LABELS

_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

_MODEL_CONFIG: dict[str, dict[str, Any]] = {
    "deberta-small": {
        "base_model_id": "cross-encoder/nli-deberta-v3-small",
        "max_tokens": 512,
        "fp16": False,
        "batch_size": 16,
        "grad_accum": 1,
        "gradient_checkpointing": False,
    },
    "bge-m3": {
        "base_model_id": "MoritzLaurer/bge-m3-zeroshot-v2.0",
        "max_tokens": 512,
        "fp16": True,
        "batch_size": 4,
        "grad_accum": 4,
        "gradient_checkpointing": True,
    },
}

# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def load_and_prepare_data(score_file: Path) -> tuple[list[str], list[str]]:
    """Load email_score.jsonl and return (texts, labels) ready for training.

    - Drops rows with non-canonical labels (warns).
    - Drops classes with < 2 total samples (warns).
    - Warns (but continues) for classes with < 5 training samples.
    - Input text format: 'subject [SEP] body[:400]'
    """
    if not score_file.exists():
        raise FileNotFoundError(
            f"Score file not found: {score_file}\n"
            "Run the label tool first to create email_score.jsonl"
        )

    lines = score_file.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(l) for l in lines if l.strip()]

    # Drop non-canonical labels
    canonical = set(LABELS)
    kept = []
    for r in rows:
        lbl = r.get("label", "")
        if lbl not in canonical:
            print(f"[data] Dropping row with non-canonical label: {lbl!r}", flush=True)
            continue
        kept.append(r)

    # Count samples per class
    from collections import Counter
    counts = Counter(r["label"] for r in kept)

    # Drop classes with < 2 total samples
    drop_classes = {lbl for lbl, cnt in counts.items() if cnt < 2}
    for lbl in sorted(drop_classes):
        print(
            f"[data] WARNING: Dropping class {lbl!r} — only {counts[lbl]} total sample(s). "
            "Need at least 2 for stratified split.",
            flush=True,
        )
    kept = [r for r in kept if r["label"] not in drop_classes]

    # Warn for classes with < 5 samples (after drops)
    counts = Counter(r["label"] for r in kept)
    for lbl, cnt in sorted(counts.items()):
        if cnt < 5:
            print(
                f"[data] WARNING: Class {lbl!r} has only {cnt} sample(s). "
                "Eval F1 for this class will be unreliable.",
                flush=True,
            )

    texts = [f"{r['subject']} [SEP] {r['body'][:400]}" for r in kept]
    labels = [r["label"] for r in kept]
    return texts, labels


# ---------------------------------------------------------------------------
# Class weights
# ---------------------------------------------------------------------------

def compute_class_weights(label_ids: list[int], n_classes: int) -> torch.Tensor:
    """Compute per-class weights: total / (n_classes * class_count).

    Returns a CPU float tensor of shape (n_classes,).
    """
    from collections import Counter
    counts = Counter(label_ids)
    total = len(label_ids)
    weights = []
    for i in range(n_classes):
        cnt = counts.get(i, 1)  # avoid division by zero for unseen classes
        weights.append(total / (n_classes * cnt))
    return torch.tensor(weights, dtype=torch.float32)


# ---------------------------------------------------------------------------
# compute_metrics callback for Trainer
# ---------------------------------------------------------------------------

def compute_metrics_for_trainer(eval_pred: EvalPrediction) -> dict:
    """Trainer callback: EvalPrediction → {macro_f1, accuracy}.

    Distinct from compute_metrics() in classifier_adapters.py (which operates
    on string predictions). This one operates on numpy logits + label_ids.
    """
    logits, labels = eval_pred
    preds = logits.argmax(axis=-1)
    return {
        "macro_f1": f1_score(labels, preds, average="macro", zero_division=0),
        "accuracy": accuracy_score(labels, preds),
    }
```

- [ ] **Step 2: Run data pipeline tests**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_finetune.py -k "load_and_prepare or class_weights or compute_metrics_for_trainer" -v
```

Expected: All 7 tests PASS. (Note: `compute_metrics_for_trainer` test requires transformers — run in `job-seeker-classifiers` env if needed.)

```bash
/devl/miniconda3/envs/job-seeker-classifiers/bin/pytest tests/test_finetune.py -k "load_and_prepare or class_weights or compute_metrics_for_trainer" -v
```

Expected: All 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add scripts/finetune_classifier.py tests/test_finetune.py
git commit -m "feat(avocet): add finetune data pipeline + class weights + compute_metrics"
```

---

### Task 8: WeightedTrainer — write failing tests

**Files:**
- Modify: `tests/test_finetune.py`

- [ ] **Step 1: Append WeightedTrainer tests**

Append to `tests/test_finetune.py`:

```python

# ---- WeightedTrainer tests ----

def test_weighted_trainer_compute_loss_returns_scalar():
    """compute_loss must return a scalar tensor when return_outputs=False."""
    import torch
    from unittest.mock import MagicMock
    from scripts.finetune_classifier import WeightedTrainer

    # Minimal mock model that returns logits
    n_classes = 3
    batch = 4
    logits = torch.randn(batch, n_classes)

    mock_outputs = MagicMock()
    mock_outputs.logits = logits

    mock_model = MagicMock(return_value=mock_outputs)

    # Build a trainer with class weights
    weights = torch.ones(n_classes)
    trainer = WeightedTrainer.__new__(WeightedTrainer)
    trainer.class_weights = weights

    inputs = {
        "input_ids": torch.zeros(batch, 10, dtype=torch.long),
        "labels": torch.randint(0, n_classes, (batch,)),
    }

    loss = trainer.compute_loss(mock_model, inputs, return_outputs=False)
    assert isinstance(loss, torch.Tensor)
    assert loss.ndim == 0  # scalar


def test_weighted_trainer_compute_loss_accepts_kwargs():
    """compute_loss must not raise TypeError when called with num_items_in_batch kwarg.

    Transformers 4.38+ passes this extra kwarg — **kwargs absorbs it.
    """
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

    # Must not raise TypeError
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
    # All labels are class 0 (majority class scenario)
    labels = torch.zeros(batch, dtype=torch.long)
    logits = torch.zeros(batch, n_classes)  # neutral logits

    mock_outputs = MagicMock()
    mock_outputs.logits = logits

    # Uniform weights
    trainer_uniform = WeightedTrainer.__new__(WeightedTrainer)
    trainer_uniform.class_weights = torch.ones(n_classes)
    inputs_uniform = {"input_ids": torch.zeros(batch, 5, dtype=torch.long), "labels": labels.clone()}
    loss_uniform = trainer_uniform.compute_loss(MagicMock(return_value=mock_outputs),
                                                inputs_uniform)

    # Heavily imbalanced weights: class 1 much more important
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_finetune.py -k "weighted_trainer" -v
```

Expected: `ImportError` — `WeightedTrainer` not yet defined.

---

### Task 9: Implement WeightedTrainer

**Files:**
- Modify: `scripts/finetune_classifier.py`

- [ ] **Step 1: Add WeightedTrainer class**

Append to `scripts/finetune_classifier.py` after `compute_metrics_for_trainer`:

```python
# ---------------------------------------------------------------------------
# Weighted Trainer
# ---------------------------------------------------------------------------

class WeightedTrainer(Trainer):
    """Trainer subclass that applies per-class weights to cross-entropy loss.

    Handles class imbalance by down-weighting majority classes and up-weighting
    minority classes. Attach class_weights (CPU float tensor) before training.
    """

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        # **kwargs is required — absorbs num_items_in_batch added in Transformers 4.38.
        # Do not remove it; removing it causes TypeError on the first training step.
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        # Move class_weights to the same device as logits — required for GPU training.
        # class_weights is created on CPU; logits are on cuda:0 during training.
        weight = self.class_weights.to(outputs.logits.device)
        loss = F.cross_entropy(outputs.logits, labels, weight=weight)
        return (loss, outputs) if return_outputs else loss
```

- [ ] **Step 2: Run WeightedTrainer tests**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_finetune.py -k "weighted_trainer" -v
```

Expected: 4 tests PASS.

- [ ] **Step 3: Run full test_finetune.py**

```bash
/devl/miniconda3/envs/job-seeker-classifiers/bin/pytest tests/test_finetune.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/finetune_classifier.py tests/test_finetune.py
git commit -m "feat(avocet): add WeightedTrainer with device-aware class weights"
```

---

### Task 10: Implement run_finetune() and CLI

**Files:**
- Modify: `scripts/finetune_classifier.py`

- [ ] **Step 1: Add run_finetune() and CLI to finetune_classifier.py**

Append to `scripts/finetune_classifier.py`:

```python
# ---------------------------------------------------------------------------
# Training dataset wrapper
# ---------------------------------------------------------------------------

from torch.utils.data import Dataset as TorchDataset


class _EmailDataset(TorchDataset):
    def __init__(self, encodings: dict, label_ids: list[int]) -> None:
        self.encodings = encodings
        self.label_ids = label_ids

    def __len__(self) -> int:
        return len(self.label_ids)

    def __getitem__(self, idx: int) -> dict:
        item = {k: torch.tensor(v[idx]) for k, v in self.encodings.items()}
        item["labels"] = torch.tensor(self.label_ids[idx], dtype=torch.long)
        return item


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------

def run_finetune(model_key: str, epochs: int = 5) -> None:
    """Fine-tune the specified model on data/email_score.jsonl.

    Saves model + tokenizer + training_info.json to models/avocet-{model_key}/.
    All prints use flush=True for SSE streaming.
    """
    if model_key not in _MODEL_CONFIG:
        raise ValueError(f"Unknown model key: {model_key!r}. Choose from: {list(_MODEL_CONFIG)}")

    config = _MODEL_CONFIG[model_key]
    base_model_id = config["base_model_id"]
    output_dir = _ROOT / "models" / f"avocet-{model_key}"

    print(f"[finetune] Model: {model_key} ({base_model_id})", flush=True)
    print(f"[finetune] Output: {output_dir}", flush=True)
    if output_dir.exists():
        print(f"[finetune] WARNING: {output_dir} already exists — will overwrite.", flush=True)

    # --- Data ---
    score_file = _ROOT / "data" / "email_score.jsonl"
    print(f"[finetune] Loading data from {score_file} ...", flush=True)
    texts, str_labels = load_and_prepare_data(score_file)

    present_labels = sorted(set(str_labels))
    label2id = {l: i for i, l in enumerate(present_labels)}
    id2label = {i: l for l, i in label2id.items()}
    n_classes = len(present_labels)
    label_ids = [label2id[l] for l in str_labels]

    print(f"[finetune] {len(texts)} samples, {n_classes} classes", flush=True)

    # Stratified 80/20 split
    (train_texts, val_texts,
     train_label_ids, val_label_ids) = train_test_split(
        texts, label_ids,
        test_size=0.2,
        stratify=label_ids,
        random_state=42,
    )
    print(f"[finetune] Train: {len(train_texts)}, Val: {len(val_texts)}", flush=True)

    # Warn for classes with < 5 training samples
    from collections import Counter
    train_counts = Counter(train_label_ids)
    for cls_id, cnt in train_counts.items():
        if cnt < 5:
            print(
                f"[finetune] WARNING: Class {id2label[cls_id]!r} has {cnt} training sample(s). "
                "Eval F1 for this class will be unreliable.",
                flush=True,
            )

    # --- Tokenize ---
    print(f"[finetune] Loading tokenizer ...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(base_model_id)

    train_enc = tokenizer(train_texts, truncation=True,
                          max_length=config["max_tokens"], padding=True)
    val_enc   = tokenizer(val_texts,   truncation=True,
                          max_length=config["max_tokens"], padding=True)

    train_dataset = _EmailDataset(train_enc, train_label_ids)
    val_dataset   = _EmailDataset(val_enc,   val_label_ids)

    # --- Class weights ---
    class_weights = compute_class_weights(train_label_ids, n_classes)
    print(f"[finetune] Class weights: {dict(zip(present_labels, class_weights.tolist()))}", flush=True)

    # --- Model ---
    print(f"[finetune] Loading model ...", flush=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model_id,
        num_labels=n_classes,
        ignore_mismatched_sizes=True,   # NLI head (3-class) → new head (n_classes)
        id2label=id2label,
        label2id=label2id,
    )
    if config["gradient_checkpointing"]:
        model.gradient_checkpointing_enable()

    # --- TrainingArguments ---
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=config["batch_size"],
        per_device_eval_batch_size=config["batch_size"],
        gradient_accumulation_steps=config["grad_accum"],
        learning_rate=2e-5,
        lr_scheduler_type="linear",
        warmup_ratio=0.1,
        fp16=config["fp16"],
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        logging_steps=10,
        report_to="none",
        save_total_limit=2,
    )

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics_for_trainer,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )
    trainer.class_weights = class_weights

    # --- Train ---
    print(f"[finetune] Starting training ({epochs} epochs) ...", flush=True)
    train_result = trainer.train()
    print(f"[finetune] Training complete. Steps: {train_result.global_step}", flush=True)

    # --- Evaluate ---
    print(f"[finetune] Evaluating best checkpoint ...", flush=True)
    metrics = trainer.evaluate()
    val_macro_f1 = metrics.get("eval_macro_f1", 0.0)
    val_accuracy = metrics.get("eval_accuracy", 0.0)
    print(f"[finetune] Val macro-F1: {val_macro_f1:.4f}, Accuracy: {val_accuracy:.4f}", flush=True)

    # --- Save model + tokenizer ---
    print(f"[finetune] Saving model to {output_dir} ...", flush=True)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    # --- Write training_info.json ---
    from collections import Counter
    label_counts = dict(Counter(str_labels))
    info = {
        "name": f"avocet-{model_key}",
        "base_model_id": base_model_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epochs_run": epochs,
        "val_macro_f1": round(val_macro_f1, 4),
        "val_accuracy": round(val_accuracy, 4),
        "sample_count": len(train_texts),
        "label_counts": label_counts,
    }
    info_path = output_dir / "training_info.json"
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"[finetune] Saved training_info.json: val_macro_f1={val_macro_f1:.4f}", flush=True)
    print(f"[finetune] Done.", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune an email classifier")
    parser.add_argument(
        "--model",
        choices=list(_MODEL_CONFIG),
        required=True,
        help="Model key to fine-tune",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=5,
        help="Number of training epochs (default: 5)",
    )
    args = parser.parse_args()
    run_finetune(args.model, args.epochs)
```

- [ ] **Step 2: Run all finetune tests**

```bash
/devl/miniconda3/envs/job-seeker-classifiers/bin/pytest tests/test_finetune.py -v
```

Expected: All tests PASS (run_finetune itself is tested in the integration test — Task 11).

- [ ] **Step 3: Commit**

```bash
git add scripts/finetune_classifier.py
git commit -m "feat(avocet): add run_finetune() training loop and CLI"
```

---

### Task 11: Integration test — finetune on example data

**Files:**
- Modify: `tests/test_finetune.py`

The example file `data/email_score.jsonl.example` has 8 samples with 5 of 10 labels represented. The 5 missing labels trigger the `< 2 total samples` drop path.

- [ ] **Step 1: Append integration test**

Append to `tests/test_finetune.py`:

```python

# ---- Integration test ----

def test_integration_finetune_on_example_data(tmp_path):
    """Fine-tune deberta-small on example data for 1 epoch.

    Uses data/email_score.jsonl.example (8 samples, 5 labels represented).
    The 5 missing labels must trigger the < 2 samples drop warning.
    Verifies training_info.json is written with correct keys.

    NOTE: This test requires the job-seeker-classifiers conda env and downloads
    the deberta-small model on first run (~100MB). Skip in CI if model not cached.
    Mark with @pytest.mark.slow to exclude from default runs.
    """
    import shutil
    from scripts.finetune_classifier import run_finetune, _ROOT
    from scripts import finetune_classifier as ft_mod

    example_file = _ROOT / "data" / "email_score.jsonl.example"
    if not example_file.exists():
        pytest.skip("email_score.jsonl.example not found")

    # Patch _ROOT to use tmp_path so model saves there, not production models/
    orig_root = ft_mod._ROOT
    ft_mod._ROOT = tmp_path

    # Also copy the example file to tmp_path/data/
    (tmp_path / "data").mkdir()
    shutil.copy(example_file, tmp_path / "data" / "email_score.jsonl")

    try:
        import io
        from contextlib import redirect_stdout
        captured = io.StringIO()
        with redirect_stdout(captured):
            run_finetune("deberta-small", epochs=1)
        output = captured.getvalue()
    finally:
        ft_mod._ROOT = orig_root

    # 5 missing labels should each trigger a drop warning
    from scripts.classifier_adapters import LABELS
    assert "< 2 total samples" in output or "WARNING: Dropping class" in output

    # training_info.json must exist with correct keys
    info_path = tmp_path / "models" / "avocet-deberta-small" / "training_info.json"
    assert info_path.exists(), "training_info.json not written"

    import json
    info = json.loads(info_path.read_text())
    for key in ("name", "base_model_id", "timestamp", "epochs_run",
                "val_macro_f1", "val_accuracy", "sample_count", "label_counts"):
        assert key in info, f"Missing key: {key}"

    assert info["name"] == "avocet-deberta-small"
    assert info["epochs_run"] == 1
```

- [ ] **Step 2: Run unit tests only (fast path, no model download)**

```bash
/devl/miniconda3/envs/job-seeker-classifiers/bin/pytest tests/test_finetune.py -v -k "not integration"
```

Expected: All non-integration tests PASS.

- [ ] **Step 3: Run integration test (requires model download ~100MB)**

```bash
/devl/miniconda3/envs/job-seeker-classifiers/bin/pytest tests/test_finetune.py::test_integration_finetune_on_example_data -v -s
```

Expected: PASS. Check output for drop warnings for missing labels.

- [ ] **Step 4: Commit**

```bash
git add tests/test_finetune.py
git commit -m "test(avocet): add integration test for finetune_classifier on example data"
```

---

## Chunk 3: API Endpoints + BenchmarkView UI

### Task 12: API endpoints — write failing tests

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Append finetune endpoint tests**

Append to `tests/test_api.py`:

```python

# ---- /api/finetune/status tests ----

def test_finetune_status_returns_empty_when_no_models_dir(client):
    """GET /api/finetune/status must return [] if models/ does not exist."""
    r = client.get("/api/finetune/status")
    assert r.status_code == 200
    assert r.json() == []


def test_finetune_status_returns_training_info(client, tmp_path):
    """GET /api/finetune/status must return one entry per training_info.json found."""
    import json
    from app import api as api_module

    # Create a fake models dir under tmp_path (data dir)
    models_dir = api_module._DATA_DIR.parent / "models"
    model_dir = models_dir / "avocet-deberta-small"
    model_dir.mkdir(parents=True)
    info = {
        "name": "avocet-deberta-small",
        "base_model_id": "cross-encoder/nli-deberta-v3-small",
        "val_macro_f1": 0.712,
        "timestamp": "2026-03-15T12:00:00Z",
        "sample_count": 401,
    }
    (model_dir / "training_info.json").write_text(json.dumps(info))

    r = client.get("/api/finetune/status")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "avocet-deberta-small"
    assert data[0]["val_macro_f1"] == pytest.approx(0.712)


def test_finetune_run_streams_sse_events(client):
    """GET /api/finetune/run must return text/event-stream content type."""
    import subprocess
    from unittest.mock import patch, MagicMock

    mock_proc = MagicMock()
    mock_proc.stdout = iter(["Training epoch 1\n", "Done\n"])
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock()

    with patch("subprocess.Popen", return_value=mock_proc):
        r = client.get("/api/finetune/run?model=deberta-small&epochs=1")

    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")


def test_finetune_run_emits_complete_on_success(client):
    """GET /api/finetune/run must emit a complete event on clean exit."""
    import subprocess
    from unittest.mock import patch, MagicMock

    mock_proc = MagicMock()
    mock_proc.stdout = iter(["progress line\n"])
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock()

    with patch("subprocess.Popen", return_value=mock_proc):
        r = client.get("/api/finetune/run?model=deberta-small&epochs=1")

    assert '{"type": "complete"}' in r.text


def test_finetune_run_emits_error_on_nonzero_exit(client):
    """GET /api/finetune/run must emit an error event on non-zero exit."""
    import subprocess
    from unittest.mock import patch, MagicMock

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 1
    mock_proc.wait = MagicMock()

    with patch("subprocess.Popen", return_value=mock_proc):
        r = client.get("/api/finetune/run?model=deberta-small&epochs=1")

    assert '"type": "error"' in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_api.py -k "finetune" -v
```

Expected: 404 or connection errors — endpoints not yet defined.

---

### Task 13: Implement finetune API endpoints

**Files:**
- Modify: `app/api.py`

- [ ] **Step 1: Add finetune endpoints to api.py**

In `app/api.py`, add after the benchmark endpoints section (after the `run_benchmark` function, before the `fetch_stream` function):

```python
# ---------------------------------------------------------------------------
# Fine-tune endpoints
# ---------------------------------------------------------------------------

@app.get("/api/finetune/status")
def get_finetune_status():
    """Scan models/ for training_info.json files. Returns [] if none exist."""
    models_dir = _ROOT / "models"
    if not models_dir.exists():
        return []
    results = []
    for sub in models_dir.iterdir():
        if not sub.is_dir():
            continue
        info_path = sub / "training_info.json"
        if not info_path.exists():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            results.append(info)
        except Exception:
            pass
    return results


@app.get("/api/finetune/run")
def run_finetune(model: str = "deberta-small", epochs: int = 5):
    """Spawn finetune_classifier.py and stream stdout as SSE progress events."""
    import subprocess

    python_bin = "/devl/miniconda3/envs/job-seeker-classifiers/bin/python"
    script = str(_ROOT / "scripts" / "finetune_classifier.py")
    cmd = [python_bin, script, "--model", model, "--epochs", str(epochs)]

    def generate():
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(_ROOT),
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    yield f"data: {json.dumps({'type': 'progress', 'message': line})}\n\n"
            proc.wait()
            if proc.returncode == 0:
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Process exited with code {proc.returncode}'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 2: Run finetune API tests**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_api.py -k "finetune" -v
```

Expected: All 5 finetune tests PASS.

- [ ] **Step 3: Run full API test suite**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/test_api.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat(avocet): add /api/finetune/status and /api/finetune/run endpoints"
```

---

### Task 14: BenchmarkView.vue — trained models badge row + fine-tune section

**Files:**
- Modify: `web/src/views/BenchmarkView.vue`

The BenchmarkView already has:
- Macro-F1 bar chart
- Latency bar chart
- Per-label F1 heatmap
- Benchmark run button with SSE log

Add:
1. **Trained models badge row** at the top (conditional on `fineTunedModels.length > 0`)
2. **Fine-tune section** (collapsible, at the bottom): model dropdown, epoch input, run button → SSE log, on `complete` auto-trigger benchmark run

- [ ] **Step 1: Read current BenchmarkView.vue**

```bash
cat web/src/views/BenchmarkView.vue
```

(Use this to understand the existing structure before editing — identify where to insert each new section.)

- [ ] **Step 2: Add fineTunedModels state and fetch logic**

In the `<script setup>` section, add after the existing reactive state:

```ts
// Fine-tuned models
const fineTunedModels = ref<Array<{
  name: string
  base_model: string
  val_macro_f1: number
  timestamp: string
  sample_count: number
}>>([])

const finetune = reactive({
  model: 'deberta-small',
  epochs: 5,
  running: false,
  log: [] as string[],
  es: null as EventSource | null,
})

async function fetchFineTunedModels() {
  try {
    const r = await fetch('/api/finetune/status')
    fineTunedModels.value = await r.json()
  } catch { /* silent */ }
}

function runFinetune() {
  if (finetune.running) return
  finetune.running = true
  finetune.log = []
  finetune.es?.close()

  const url = `/api/finetune/run?model=${finetune.model}&epochs=${finetune.epochs}`
  finetune.es = new EventSource(url)
  finetune.es.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.type === 'progress') {
      finetune.log.push(msg.message)
    } else if (msg.type === 'complete') {
      finetune.running = false
      finetune.es?.close()
      fetchFineTunedModels()
      runBenchmark()  // auto-trigger benchmark to update charts
    } else if (msg.type === 'error') {
      finetune.running = false
      finetune.es?.close()
      finetune.log.push(`ERROR: ${msg.message}`)
    }
  }
}
```

Add `fetchFineTunedModels()` to the `onMounted` call alongside the existing `fetchResults()`.

- [ ] **Step 3: Add trained models badge row to template**

In the `<template>`, add at the very top of the main content area (before the chart sections), conditional on `fineTunedModels.length > 0`:

```html
<!-- Trained models badge row -->
<div v-if="fineTunedModels.length > 0" class="trained-models-row">
  <span class="trained-label">Trained models:</span>
  <span
    v-for="m in fineTunedModels"
    :key="m.name"
    class="trained-badge"
    :title="`Base: ${m.base_model} | ${m.sample_count} samples | ${m.timestamp}`"
  >
    {{ m.name }}
    <span class="trained-f1">F1 {{ (m.val_macro_f1 * 100).toFixed(1) }}%</span>
  </span>
</div>
```

- [ ] **Step 4: Add fine-tune collapsible section to template**

Add at the bottom of the main content area, after the benchmark log section:

```html
<!-- Fine-tune section -->
<details class="finetune-section">
  <summary class="finetune-summary">Fine-tune a model</summary>
  <div class="finetune-controls">
    <label class="ft-label">
      Model
      <select v-model="finetune.model" class="ft-select">
        <option value="deberta-small">deberta-small (100M, fast)</option>
        <option value="bge-m3">bge-m3 (600M, slow — stop Peregrine vLLM first)</option>
      </select>
    </label>
    <label class="ft-label">
      Epochs
      <input
        v-model.number="finetune.epochs"
        type="number"
        min="1"
        max="20"
        class="ft-epochs"
      />
    </label>
    <button
      class="ft-run-btn"
      :disabled="finetune.running"
      @click="runFinetune"
    >
      {{ finetune.running ? 'Training…' : 'Run fine-tune' }}
    </button>
  </div>
  <div v-if="finetune.log.length > 0" class="ft-log">
    <div v-for="(line, i) in finetune.log" :key="i" class="ft-log-line">{{ line }}</div>
  </div>
</details>
```

- [ ] **Step 5: Add styles**

Add to the `<style scoped>` section:

```css
/* Trained models badge row */
.trained-models-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: var(--color-surface-raised, #e4ebf5);
  border-radius: 0.5rem;
  margin-bottom: 1rem;
}

.trained-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.trained-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.6rem;
  background: var(--app-primary, #2A6080);
  color: white;
  border-radius: 1rem;
  font-size: 0.82rem;
  cursor: default;
}

.trained-f1 {
  background: rgba(255,255,255,0.2);
  border-radius: 0.75rem;
  padding: 0.1rem 0.4rem;
  font-size: 0.75rem;
  font-weight: 700;
}

/* Fine-tune section */
.finetune-section {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  padding: 0;
  margin-top: 1.5rem;
}

.finetune-summary {
  padding: 0.75rem 1rem;
  cursor: pointer;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  list-style: none;
  user-select: none;
}

.finetune-summary::-webkit-details-marker { display: none; }

.finetune-summary::before {
  content: '▶ ';
  font-size: 0.7rem;
  color: var(--color-text-secondary, #6b7a99);
}

details[open] .finetune-summary::before { content: '▼ '; }

.finetune-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: flex-end;
  padding: 0.75rem 1rem 1rem;
  border-top: 1px solid var(--color-border, #d0d7e8);
}

.ft-label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
}

.ft-select {
  padding: 0.35rem 0.6rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #f0f4fb);
  font-size: 0.9rem;
  color: var(--color-text, #1a2338);
  min-width: 260px;
}

.ft-epochs {
  width: 70px;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #f0f4fb);
  font-size: 0.9rem;
  color: var(--color-text, #1a2338);
  text-align: center;
}

.ft-run-btn {
  padding: 0.45rem 1.2rem;
  background: var(--app-primary, #2A6080);
  color: white;
  border: none;
  border-radius: 0.375rem;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}

.ft-run-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.ft-log {
  margin: 0 1rem 1rem;
  padding: 0.5rem 0.75rem;
  background: var(--color-surface, #f0f4fb);
  border-radius: 0.375rem;
  max-height: 260px;
  overflow-y: auto;
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}

.ft-log-line {
  line-height: 1.6;
  color: var(--color-text, #1a2338);
  white-space: pre-wrap;
  word-break: break-all;
}
```

- [ ] **Step 6: Build and verify**

```bash
cd /Library/Development/CircuitForge/avocet/web && npm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 7: Start dev server and verify in browser**

```bash
./manage.sh start-api
```

Open http://localhost:8503 → navigate to Benchmark:
- Badge row not visible (no trained models yet — correct)
- Fine-tune section visible as collapsed `<details>`
- Click to expand → dropdown and epoch input visible
- Without a model trained, status returns `[]` (correct)

- [ ] **Step 8: Commit**

```bash
git add web/src/views/BenchmarkView.vue
git commit -m "feat(avocet): add fine-tune section and trained models badge row to BenchmarkView"
```

---

### Task 15: Final verification — full test suite

- [ ] **Step 1: Run full test suite**

```bash
/devl/miniconda3/envs/job-seeker/bin/pytest tests/ -v -k "not integration"
```

Expected: All non-integration tests PASS.

- [ ] **Step 2: Run in classifier env (catches transformers-specific tests)**

```bash
/devl/miniconda3/envs/job-seeker-classifiers/bin/pytest tests/ -v -k "not integration"
```

Expected: All non-integration tests PASS.

- [ ] **Step 3: Build Vue SPA**

```bash
cd /Library/Development/CircuitForge/avocet/web && npm run build
```

Expected: No TypeScript or build errors.

- [ ] **Step 4: Final commit**

```bash
git add -A
git status  # verify nothing unexpected staged
git commit -m "feat(avocet): finetune classifier feature complete"
```
