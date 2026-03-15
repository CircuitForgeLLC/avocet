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
from collections import Counter
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


def load_and_prepare_data(score_file: Path) -> tuple[list[str], list[str]]:
    """Load labeled JSONL and return (texts, labels) filtered to canonical LABELS.

    Drops rows with non-canonical labels (with warning), and drops entire classes
    that have fewer than 2 total samples (required for stratified split).
    Warns (but continues) for classes with fewer than 5 samples.
    """
    if not score_file.exists():
        raise FileNotFoundError(
            f"Labeled data not found: {score_file}\n"
            "Run the label tool first to generate email_score.jsonl."
        )

    label_set = set(LABELS)
    rows: list[dict] = []

    with score_file.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            lbl = r.get("label", "")
            if lbl not in label_set:
                print(
                    f"[data] WARNING: Dropping row with non-canonical label {lbl!r}",
                    flush=True,
                )
                continue
            rows.append(r)

    # Count samples per class
    counts: Counter = Counter(r["label"] for r in rows)

    # Drop classes with < 2 total samples (cannot stratify-split)
    drop_classes: set[str] = set()
    for lbl, cnt in counts.items():
        if cnt < 2:
            print(
                f"[data] WARNING: Dropping class {lbl!r} — only {counts[lbl]} total "
                f"sample(s). Need at least 2 for stratified split.",
                flush=True,
            )
            drop_classes.add(lbl)

    # Warn for classes with < 5 samples (unreliable eval F1)
    for lbl, cnt in counts.items():
        if lbl not in drop_classes and cnt < 5:
            print(
                f"[data] WARNING: Class {lbl!r} has only {cnt} sample(s). "
                f"Eval F1 for this class will be unreliable.",
                flush=True,
            )

    # Filter rows
    rows = [r for r in rows if r["label"] not in drop_classes]

    texts = [f"{r['subject']} [SEP] {r['body'][:400]}" for r in rows]
    labels = [r["label"] for r in rows]

    return texts, labels


def compute_class_weights(label_ids: list[int], n_classes: int) -> torch.Tensor:
    """Compute inverse-frequency class weights.

    Formula: total / (n_classes * class_count) per class.
    Unseen classes (count=0) use count=1 to avoid division by zero.

    Returns a CPU float32 tensor of shape (n_classes,).
    """
    counts = Counter(label_ids)
    total = len(label_ids)
    weights = []
    for cls in range(n_classes):
        cnt = counts.get(cls, 1)  # use 1 for unseen to avoid div-by-zero
        weights.append(total / (n_classes * cnt))
    return torch.tensor(weights, dtype=torch.float32)


def compute_metrics_for_trainer(eval_pred: EvalPrediction) -> dict:
    """Compute macro F1 and accuracy from EvalPrediction.

    Called by Hugging Face Trainer at each evaluation step.
    """
    logits, label_ids = eval_pred.predictions, eval_pred.label_ids
    preds = logits.argmax(axis=-1)
    macro_f1 = f1_score(label_ids, preds, average="macro", zero_division=0)
    acc = accuracy_score(label_ids, preds)
    return {"macro_f1": float(macro_f1), "accuracy": float(acc)}


class WeightedTrainer(Trainer):
    """Trainer subclass that applies per-class weights to the cross-entropy loss."""

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
