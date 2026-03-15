# Fine-tune Email Classifier — Design Spec

**Date:** 2026-03-15
**Status:** Approved
**Scope:** Avocet — `scripts/`, `app/api.py`, `web/src/views/BenchmarkView.vue`, `environment.yml`

---

## Problem

The benchmark baseline shows zero-shot macro-F1 of 0.366 for the best models (`deberta-zeroshot`, `deberta-base-anli`). Zero-shot inference cannot improve with more labeled data. Fine-tuning the fastest models (`deberta-small` at 111ms, `bge-m3` at 123ms) on the growing labeled dataset is the path to meaningful accuracy gains.

---

## Constraints

- 501 labeled samples after dropping 2 non-canonical `profile_alert` rows
- Heavy class imbalance: `digest` 29%, `neutral` 26%, `new_lead` 2.6%, `survey_received` 3%
- 8.2 GB VRAM (shared with Peregrine vLLM during dev)
- Target models: `cross-encoder/nli-deberta-v3-small` (100M params), `MoritzLaurer/bge-m3-zeroshot-v2.0` (600M params)
- Output: local `models/avocet-{name}/` directory
- UI-triggerable via web interface (SSE streaming log)
- Stack: transformers 4.57.3, torch 2.10.0, accelerate 1.12.0, sklearn, CUDA 8.2GB

---

## Environment changes

`environment.yml` must add:
- `scikit-learn` — required for `train_test_split(stratify=...)` and `f1_score`
- `peft` is NOT used by this spec; it is available in the env but not required here

---

## Architecture

### New file: `scripts/finetune_classifier.py`

CLI entry point for fine-tuning. All prints use `flush=True` so stdout is SSE-streamable.

```
python scripts/finetune_classifier.py --model deberta-small [--epochs 5]
```

Supported `--model` values: `deberta-small`, `bge-m3`

**Model registry** (internal to this script):

| Key | Base model ID | Max tokens | fp16 | Batch size | Grad accum steps | Gradient checkpointing |
|-----|--------------|------------|------|------------|-----------------|----------------------|
| `deberta-small` | `cross-encoder/nli-deberta-v3-small` | 512 | No | 16 | 1 | No |
| `bge-m3` | `MoritzLaurer/bge-m3-zeroshot-v2.0` | 512 | Yes | 4 | 4 | Yes |

`bge-m3` uses `fp16=True` (halves optimizer state from ~4.8GB to ~2.4GB) with batch size 4 + gradient accumulation 4 = effective batch 16, matching `deberta-small`. These settings are required to fit within 8.2GB VRAM. Still stop Peregrine vLLM before running bge-m3 fine-tuning.

### Modified: `scripts/classifier_adapters.py`

Add `FineTunedAdapter(ClassifierAdapter)`:
- Takes `model_dir: str` (path to a `models/avocet-*/` checkpoint)
- Loads via `pipeline("text-classification", model=model_dir)`
- `classify()` input format: **`f"{subject} [SEP] {body[:400]}"`** — must match the training format exactly. Do NOT use the zero-shot adapters' `f"Subject: {subject}\n\n{body[:600]}"` format; distribution shift will degrade accuracy.
- Returns the top predicted label directly (single forward pass — no per-label NLI scoring loop)
- Expected inference speed: ~10–20ms/email vs 111–338ms for zero-shot

### Modified: `scripts/benchmark_classifier.py`

At startup, scan `models/` for subdirectories containing `training_info.json`. Register each as a dynamic entry in the model registry using `FineTunedAdapter`. Silently skips if `models/` does not exist. Existing CLI behaviour unchanged.

### Modified: `app/api.py`

Two new GET endpoints (GET required for `EventSource` compatibility):

**`GET /api/finetune/status`**
Scans `models/` for `training_info.json` files. Returns:
```json
[
  {
    "name": "avocet-deberta-small",
    "base_model": "cross-encoder/nli-deberta-v3-small",
    "val_macro_f1": 0.712,
    "timestamp": "2026-03-15T12:00:00Z",
    "sample_count": 401
  }
]
```
Returns `[]` if no fine-tuned models exist.

**`GET /api/finetune/run?model=deberta-small&epochs=5`**
Spawns `finetune_classifier.py` via the `job-seeker-classifiers` Python binary. Streams stdout as SSE `{"type":"progress","message":"..."}` events. Emits `{"type":"complete"}` on clean exit, `{"type":"error","message":"..."}` on non-zero exit. Same implementation pattern as `/api/benchmark/run`.

### Modified: `web/src/views/BenchmarkView.vue`

**Trained models badge row** (top of view, conditional on fine-tuned models existing):
Shows each fine-tuned model name + val macro-F1 chip. Fetches from `/api/finetune/status` on mount.

**Fine-tune section** (collapsible, below benchmark charts):
- Dropdown: `deberta-small` | `bge-m3`
- Number input: epochs (default 5, range 1–20)
- Run button → streams into existing log component
- On `complete`: auto-triggers `/api/benchmark/run` (with `--save`) so charts update immediately

---

## Training Pipeline

### Data preparation

1. Load `data/email_score.jsonl`
2. Drop rows where `label` not in canonical `LABELS` (removes `profile_alert` etc.)
3. Check for classes with < 2 **total** samples (before any split). Drop those classes and warn. Additionally warn — but do not skip — classes with < 5 training samples, noting eval F1 for those classes will be unreliable.
4. Input text: `f"{subject} [SEP] {body[:400]}"` — fits within 512 tokens for both target models
5. Stratified 80/20 train/val split via `sklearn.model_selection.train_test_split(stratify=labels)`

### Class weighting

Compute per-class weights: `total_samples / (n_classes × class_count)`. Pass to a `WeightedTrainer` subclass:

```python
class WeightedTrainer(Trainer):
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

### Model setup

```python
AutoModelForSequenceClassification.from_pretrained(
    base_model_id,
    num_labels=10,
    ignore_mismatched_sizes=True,   # see note below
    id2label=id2label,
    label2id=label2id,
)
```

**Note on `ignore_mismatched_sizes=True`:** The pretrained NLI head is a 3-class linear projection. It mismatches the 10-class head constructed by `num_labels=10`, so its weights are skipped during loading. PyTorch initializes the new head from scratch using the model's default init scheme. The backbone weights load normally. Do not set this to `False` — it will raise a shape error.

### Training config and `compute_metrics`

The Trainer requires a `compute_metrics` callback that takes an `EvalPrediction` (logits + label_ids) and returns a dict with a `macro_f1` key. This is distinct from the existing `compute_metrics` in `classifier_adapters.py` (which operates on string predictions):

```python
def compute_metrics_for_trainer(eval_pred: EvalPrediction) -> dict:
    logits, labels = eval_pred
    preds = logits.argmax(axis=-1)
    return {
        "macro_f1": f1_score(labels, preds, average="macro", zero_division=0),
        "accuracy": accuracy_score(labels, preds),
    }
```

`TrainingArguments` must include:
- `load_best_model_at_end=True`
- `metric_for_best_model="macro_f1"`
- `greater_is_better=True`

These are required for `EarlyStoppingCallback` to work correctly. Without `load_best_model_at_end=True`, `EarlyStoppingCallback` raises `AssertionError` on init.

| Hyperparameter | deberta-small | bge-m3 |
|---------------|--------------|--------|
| Epochs | 5 (default, CLI-overridable) | 5 |
| Batch size | 16 | 4 |
| Gradient accumulation | 1 | 4 (effective batch = 16) |
| Learning rate | 2e-5 | 2e-5 |
| LR schedule | Linear with 10% warmup | same |
| Optimizer | AdamW | AdamW |
| fp16 | No | Yes |
| Gradient checkpointing | No | Yes |
| Eval strategy | Every epoch | Every epoch |
| Best checkpoint | By `macro_f1` | same |
| Early stopping patience | 3 epochs | 3 epochs |

### Output

Saved to `models/avocet-{name}/`:
- Model weights + tokenizer (standard HuggingFace format)
- `training_info.json`:
```json
{
  "name": "avocet-deberta-small",
  "base_model_id": "cross-encoder/nli-deberta-v3-small",
  "timestamp": "2026-03-15T12:00:00Z",
  "epochs_run": 5,
  "val_macro_f1": 0.712,
  "val_accuracy": 0.798,
  "sample_count": 401,
  "label_counts": { "digest": 116, "neutral": 104, ... }
}
```

---

## Data Flow

```
email_score.jsonl
      │
      ▼
finetune_classifier.py
  ├── drop non-canonical labels
  ├── check for < 2 total samples per class (drop + warn)
  ├── stratified 80/20 split
  ├── tokenize (subject [SEP] body[:400])
  ├── compute class weights
  ├── WeightedTrainer + EarlyStoppingCallback
  └── save → models/avocet-{name}/
                    │
                    ├── FineTunedAdapter (classifier_adapters.py)
                    │       ├── pipeline("text-classification")
                    │       ├── input: subject [SEP] body[:400]   ← must match training format
                    │       └── ~10–20ms/email inference
                    │
                    └── training_info.json
                            └── /api/finetune/status
                                        └── BenchmarkView badge row
```

---

## Error Handling

- **Insufficient data (< 2 total samples in a class):** Drop class before split, print warning with class name and count.
- **Low data warning (< 5 training samples in a class):** Warn but continue; note eval F1 for that class will be unreliable.
- **VRAM OOM on bge-m3:** Surface as clear SSE error message. Suggest stopping Peregrine vLLM first (it holds ~5.7GB).
- **Missing score file:** Raise `FileNotFoundError` with actionable message (same pattern as `load_scoring_jsonl`).
- **Model dir already exists:** Overwrite with a warning log line. Re-running always produces a fresh checkpoint.

---

## Testing

- Unit test `WeightedTrainer.compute_loss` with a mock model and known label distribution — verify weighted loss differs from unweighted; verify `**kwargs` does not raise `TypeError`
- Unit test `compute_metrics_for_trainer` — verify `macro_f1` key in output, correct value on known inputs
- Unit test `FineTunedAdapter.classify` with a mock pipeline — verify it returns a string from `LABELS` using `subject [SEP] body[:400]` format
- Unit test auto-discovery in `benchmark_classifier.py` — mock `models/` dir with two `training_info.json` files, verify both appear in the active registry
- Integration test: fine-tune on `data/email_score.jsonl.example` (8 samples, 5 of 10 labels represented, 1 epoch, `--model deberta-small`). The 5 missing labels trigger the `< 2 total samples` drop path — the test must verify the drop warning is emitted for each missing label rather than treating it as a failure. Verify `models/avocet-deberta-small/training_info.json` is written with correct keys.

---

## Out of Scope

- Pushing fine-tuned weights to HuggingFace Hub (future)
- Cross-validation or k-fold evaluation (future — dataset too small to be meaningful now)
- Hyperparameter search (future)
- LoRA/PEFT adapter fine-tuning (future — relevant if model sizes grow beyond available VRAM)
- Fine-tuning models other than `deberta-small` and `bge-m3`
