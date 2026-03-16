"""Fine-tune email classifiers on the labeled dataset.

CLI entry point. All prints use flush=True so stdout is SSE-streamable.

Usage:
    python scripts/finetune_classifier.py --model deberta-small [--epochs 5]

Supported --model values: deberta-small, bge-m3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset as TorchDataset
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
        # fp16 must stay OFF — DeBERTa-v3 disentangled attention overflows fp16.
        "fp16": False,
        # batch_size=8 + grad_accum=2 keeps effective batch of 16 while halving
        # per-step activation memory. gradient_checkpointing recomputes activations
        # on backward instead of storing them — ~60% less activation VRAM.
        "batch_size": 8,
        "grad_accum": 2,
        "gradient_checkpointing": True,
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


def load_and_prepare_data(score_files: Path | list[Path]) -> tuple[list[str], list[str]]:
    """Load labeled JSONL and return (texts, labels) filtered to canonical LABELS.

    score_files: a single Path or a list of Paths. When multiple files are given,
    rows are merged with last-write-wins deduplication keyed by content hash
    (MD5 of subject + body[:100]).

    Drops rows with non-canonical labels (with warning), and drops entire classes
    that have fewer than 2 total samples (required for stratified split).
    Warns (but continues) for classes with fewer than 5 samples.
    """
    # Normalise to list — backwards compatible with single-Path callers.
    if isinstance(score_files, Path):
        score_files = [score_files]

    for score_file in score_files:
        if not score_file.exists():
            raise FileNotFoundError(
                f"Labeled data not found: {score_file}\n"
                "Run the label tool first to generate email_score.jsonl."
            )

    label_set = set(LABELS)
    # Use a plain dict keyed by content hash; later entries overwrite earlier ones
    # (last-write wins), which lets later labeling runs correct earlier labels.
    seen: dict[str, dict] = {}
    total = 0

    for score_file in score_files:
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
                content_hash = hashlib.md5(
                    (r.get("subject", "") + (r.get("body", "") or "")[:100]).encode(
                        "utf-8", errors="replace"
                    )
                ).hexdigest()
                seen[content_hash] = r
                total += 1

    kept = len(seen)
    dropped = total - kept
    if dropped > 0:
        print(
            f"[data] Deduped: kept {kept} of {total} rows (dropped {dropped} duplicates)",
            flush=True,
        )

    rows = list(seen.values())

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


# ---------------------------------------------------------------------------
# Training dataset wrapper
# ---------------------------------------------------------------------------


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

def run_finetune(model_key: str, epochs: int = 5, score_files: list[Path] | None = None) -> None:
    """Fine-tune the specified model on labeled data.

    score_files: list of score JSONL paths to merge. Defaults to [_ROOT / "data" / "email_score.jsonl"].
    Saves model + tokenizer + training_info.json to models/avocet-{model_key}/.
    All prints use flush=True for SSE streaming.
    """
    if model_key not in _MODEL_CONFIG:
        raise ValueError(f"Unknown model key: {model_key!r}. Choose from: {list(_MODEL_CONFIG)}")

    if score_files is None:
        score_files = [_ROOT / "data" / "email_score.jsonl"]

    config = _MODEL_CONFIG[model_key]
    base_model_id = config["base_model_id"]
    output_dir = _ROOT / "models" / f"avocet-{model_key}"

    print(f"[finetune] Model: {model_key} ({base_model_id})", flush=True)
    print(f"[finetune] Score files: {[str(f) for f in score_files]}", flush=True)
    print(f"[finetune] Output: {output_dir}", flush=True)
    if output_dir.exists():
        print(f"[finetune] WARNING: {output_dir} already exists — will overwrite.", flush=True)

    # --- Data ---
    print(f"[finetune] Loading data ...", flush=True)
    texts, str_labels = load_and_prepare_data(score_files)

    present_labels = sorted(set(str_labels))
    label2id = {l: i for i, l in enumerate(present_labels)}
    id2label = {i: l for l, i in label2id.items()}
    n_classes = len(present_labels)
    label_ids = [label2id[l] for l in str_labels]

    print(f"[finetune] {len(texts)} samples, {n_classes} classes", flush=True)

    # Stratified 80/20 split — ensure val set has at least n_classes samples.
    # For very small datasets (e.g. example data) we may need to give the val set
    # more than 20% so every class appears at least once in eval.
    desired_test = max(int(len(texts) * 0.2), n_classes)
    # test_size must leave at least n_classes samples for train too
    desired_test = min(desired_test, len(texts) - n_classes)
    (train_texts, val_texts,
     train_label_ids, val_label_ids) = train_test_split(
        texts, label_ids,
        test_size=desired_test,
        stratify=label_ids,
        random_state=42,
    )
    print(f"[finetune] Train: {len(train_texts)}, Val: {len(val_texts)}", flush=True)

    # Warn for classes with < 5 training samples
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
    print(f"[finetune] Class weights computed", flush=True)

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
        # use_reentrant=False avoids "backward through graph a second time" errors
        # when Accelerate's gradient accumulation context is layered on top.
        # Reentrant checkpointing (the default) conflicts with Accelerate ≥ 0.27.
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )

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
    label_counts = dict(Counter(str_labels))
    info = {
        "name": f"avocet-{model_key}",
        "base_model_id": base_model_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epochs_run": epochs,
        "val_macro_f1": round(val_macro_f1, 4),
        "val_accuracy": round(val_accuracy, 4),
        "sample_count": len(texts),
        "train_sample_count": len(train_texts),
        "label_counts": label_counts,
        "score_files": [str(f) for f in score_files],
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
    parser.add_argument(
        "--score",
        dest="score_files",
        type=Path,
        action="append",
        metavar="FILE",
        help="Score JSONL file to include (repeatable; defaults to data/email_score.jsonl)",
    )
    args = parser.parse_args()
    score_files = args.score_files or None  # None → run_finetune uses default
    run_finetune(args.model, args.epochs, score_files=score_files)
