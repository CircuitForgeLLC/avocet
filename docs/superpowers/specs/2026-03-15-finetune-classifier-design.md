# Fine-tune Email Classifier — Design Spec

**Date:** 2026-03-15
**Status:** Approved
**Scope:** Avocet — `scripts/`, `app/api.py`, `web/src/views/BenchmarkView.vue`

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

---

## Architecture

### New file: `scripts/finetune_classifier.py`

CLI entry point for fine-tuning. Designed so stdout is SSE-streamable (all prints use `flush=True`).

```
python scripts/finetune_classifier.py --model deberta-small [--epochs 5]
```

Supported `--model` values: `deberta-small`, `bge-m3`

**Model registry** (internal to this script):

| Key | Base model ID | Max tokens | Gradient checkpointing |
|-----|--------------|------------|----------------------|
| `deberta-small` | `cross-encoder/nli-deberta-v3-small` | 512 | No |
| `bge-m3` | `MoritzLaurer/bge-m3-zeroshot-v2.0` | 512 | Yes |

### Modified: `scripts/classifier_adapters.py`

Add `FineTunedAdapter(ClassifierAdapter)`:
- Takes `model_dir: str` (path to a `models/avocet-*/` checkpoint)
- Loads via `pipeline("text-classification", model=model_dir)`
- `classify()` returns the top predicted label directly (single forward pass — no per-label NLI scoring loop)
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
Spawns `finetune_classifier.py` via the `job-seeker-classifiers` Python binary. Streams stdout as SSE `{"type":"progress","message":"..."}` events. Emits `{"type":"complete"}` on clean exit, `{"type":"error","message":"..."}` on non-zero exit.

### Modified: `web/src/views/BenchmarkView.vue`

**Trained models badge row** (top of view, conditional on fine-tuned models existing):
Shows each fine-tuned model name + val macro-F1 chip.

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
3. Input text: `f"{subject} [SEP] {body[:400]}"` — fits within 512 tokens for both target models
4. Stratified 80/20 train/val split via `sklearn.model_selection.train_test_split(stratify=labels)`

### Class weighting

Compute per-class weights: `total_samples / (n_classes × class_count)`. Pass to a `WeightedTrainer` subclass that overrides `compute_loss`:

```python
class WeightedTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        loss = F.cross_entropy(outputs.logits, labels, weight=self.class_weights)
        return (loss, outputs) if return_outputs else loss
```

### Model setup

```python
AutoModelForSequenceClassification.from_pretrained(
    base_model_id,
    num_labels=10,
    ignore_mismatched_sizes=True,   # drops NLI head, initialises fresh 10-class head
    id2label=id2label,
    label2id=label2id,
)
```

`ignore_mismatched_sizes=True` is required because the NLI head (3 classes) is being replaced with a 10-class head.

### Training config

| Hyperparameter | Value |
|---------------|-------|
| Epochs | 5 (default, CLI-overridable) |
| Batch size | 16 |
| Learning rate | 2e-5 |
| LR schedule | Linear with 10% warmup |
| Optimizer | AdamW |
| Eval strategy | Every epoch |
| Best checkpoint | By val macro-F1 |
| Early stopping | 3 epochs without improvement |
| Gradient checkpointing | bge-m3 only |

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
  ├── stratified 80/20 split
  ├── tokenize (subject [SEP] body[:400])
  ├── compute class weights
  ├── WeightedTrainer (HuggingFace Trainer subclass)
  └── save → models/avocet-{name}/
                    │
                    ├── FineTunedAdapter (classifier_adapters.py)
                    │       └── pipeline("text-classification")
                    │               └── ~10–20ms/email inference
                    │
                    └── training_info.json
                            └── /api/finetune/status
                                        └── BenchmarkView badge row
```

---

## Error Handling

- **Insufficient data per class:** Warn and skip classes with < 2 samples in the training split (can't stratify). Log which classes were skipped.
- **VRAM OOM:** Surface as a clear error message in the SSE stream. Suggest stopping Peregrine vLLM first.
- **Missing score file:** Raise `FileNotFoundError` with actionable message (same pattern as `load_scoring_jsonl`).
- **Model dir already exists:** Overwrite with a warning log line (re-running fine-tune should always produce a fresh checkpoint).

---

## Testing

- Unit test `WeightedTrainer.compute_loss` with a mock model and known label distribution — verify loss differs from unweighted
- Unit test `FineTunedAdapter.classify` with a mock pipeline — verify it returns a string from `LABELS`
- Unit test auto-discovery in `benchmark_classifier.py` — mock `models/` dir with two `training_info.json` files, verify both appear in the active registry
- Integration test: fine-tune on the `.example` JSONL (10 samples, 1 epoch) — verify `models/avocet-*/training_info.json` is written with correct keys

---

## Out of Scope

- Pushing fine-tuned weights to HuggingFace Hub (future)
- Cross-validation or k-fold evaluation (future — dataset too small to be meaningful now)
- Hyperparameter search (future)
- Fine-tuning models other than `deberta-small` and `bge-m3`
