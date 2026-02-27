# Avocet — Email Classifier Training Tool

## What it is

Shared infrastructure for building and benchmarking email classifiers across the CircuitForge menagerie.
Named for the avocet's sweeping-bill technique — it sweeps through email streams and filters out categories.

**Pipeline:**
```
Scrape (IMAP, wide search, multi-account) → data/email_label_queue.jsonl
                ↓
Label (card-stack UI)                      → data/email_score.jsonl
                ↓
Benchmark (HuggingFace NLI/reranker)       → per-model macro-F1 + latency
```

## Environment

- Python env: `conda run -n job-seeker <cmd>` for basic use (streamlit, yaml, stdlib only)
- Classifier env: `conda run -n job-seeker-classifiers <cmd>` for benchmark (transformers, FlagEmbedding, gliclass)
- Run tests: `/devl/miniconda3/envs/job-seeker/bin/pytest tests/ -v`
  (direct binary — `conda run pytest` can spawn runaway processes)
- Create classifier env: `conda env create -f environment.yml`

## Label Tool (app/label_tool.py)

Card-stack Streamlit UI for manually labeling recruitment emails.

```
conda run -n job-seeker streamlit run app/label_tool.py --server.port 8503
```

- Config: `config/label_tool.yaml` (gitignored — copy from `.example`, or use ⚙️ Settings tab)
- Queue: `data/email_label_queue.jsonl` (gitignored)
- Output: `data/email_score.jsonl` (gitignored)
- Four tabs: 🃏 Label, 📥 Fetch, 📊 Stats, ⚙️ Settings
- Keyboard shortcuts: 1–9 = label, 0 = Other (wildcard, prompts free-text input), S = skip, U = undo
- Dedup: MD5 of `(subject + body[:100])` — cross-account safe

### Settings Tab (⚙️)
- Add / edit / remove IMAP accounts via form UI — no manual YAML editing required
- Per-account fields: display name, host, port, SSL toggle, username, password (masked), folder, days back
- **🔌 Test connection** button per account — connects, logs in, selects folder, reports message count
- Global: max emails per account per fetch
- **💾 Save** writes `config/label_tool.yaml`; **↩ Reload** discards unsaved changes
- `_sync_settings_to_state()` collects widget values before any add/remove to avoid index-key drift

## Benchmark (scripts/benchmark_classifier.py)

```
# List available models
conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --list-models

# Score against labeled JSONL
conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --score

# Visual comparison on live IMAP emails
conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --compare --limit 20

# Include slow/large models
conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --score --include-slow

# Export DB-labeled emails (⚠️ LLM-generated labels — review first)
conda run -n job-seeker-classifiers python scripts/benchmark_classifier.py --export-db --db /path/to/staging.db
```

## Labels (peregrine defaults — configurable per product)

| Label | Key | Meaning |
|-------|-----|---------|
| `interview_scheduled` | 1 | Phone screen, video call, or on-site invitation |
| `offer_received` | 2 | Formal job offer or offer letter |
| `rejected` | 3 | Application declined or not moving forward |
| `positive_response` | 4 | Recruiter interest or request to connect |
| `survey_received` | 5 | Culture-fit survey or assessment invitation |
| `neutral` | 6 | ATS confirmation (application received, etc.) |
| `event_rescheduled` | 7 | Interview or event moved to a new time |
| `unrelated` | 8 | Non-job-search email, not classifiable |
| `digest` | 9 | Job digest or multi-listing email (scrapeable) |

## Model Registry (13 models, 7 defaults)

See `scripts/benchmark_classifier.py:MODEL_REGISTRY`.
Default models run without `--include-slow`.
Add `--models deberta-small deberta-small-2pass` to test a specific subset.

## Config Files

- `config/label_tool.yaml` — gitignored; multi-account IMAP config
- `config/label_tool.yaml.example` — committed template

## Data Files

- `data/email_score.jsonl` — gitignored; manually-labeled ground truth
- `data/email_score.jsonl.example` — committed sample for CI
- `data/email_label_queue.jsonl` — gitignored; IMAP fetch queue

## Key Design Notes

- `ZeroShotAdapter.load()` instantiates the pipeline object; `classify()` calls the object.
  Tests patch `scripts.classifier_adapters.pipeline` (the module-level factory) with a
  two-level mock: `mock_factory.return_value = MagicMock(return_value={...})`.
- `two_pass=True` on ZeroShotAdapter: first pass ranks all 6 labels; second pass re-runs
  with only top-2, forcing a binary choice. 2× cost, better confidence.
- `--compare` uses the first account in `label_tool.yaml` for live IMAP emails.
- DB export labels are llama3.1:8b-generated — treat as noisy, not gold truth.

## Relationship to Peregrine

Avocet started as `peregrine/tools/label_tool.py` + `peregrine/scripts/classifier_adapters.py`.
Peregrine retains copies during stabilization; once avocet is proven, peregrine will import from here.
