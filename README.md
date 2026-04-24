# Avocet — Email Classifier Training Tool

> *Part of the CircuitForge LLC internal infrastructure suite.*

**Status:** Internal beta — label tool and benchmark harness complete. Used to build training data for Peregrine's email classifier.

---

## What it does

Avocet is the data pipeline for building and benchmarking email classifiers. It has two layers:

**No LLM required.** Avocet uses zero-shot HuggingFace classification models — no API key, no cloud inference, no GPU required for the label tool. The benchmark harness can optionally export LLM-labeled emails from a Peregrine staging DB, but human labeling via the card-stack UI is the primary workflow.

**Layer 1 — Label tool**
Card-stack UI for building ground-truth classifier benchmark data. Fetch emails from one or more IMAP accounts (with targeted date-range and sender/subject filters), review them card-by-card, and label each with a job-search category. Labeled output feeds the benchmark harness.

**Layer 2 — Benchmark harness**
Scores HuggingFace zero-shot classification models against the labeled dataset. Supports slow/large model inclusion, visual side-by-side comparison on live emails, and export of LLM-labeled emails from a Peregrine staging DB.

---

## Labels

| Label | Key |
|-------|-----|
| `interview_scheduled` | 1 |
| `offer_received` | 2 |
| `rejected` | 3 |
| `positive_response` | 4 |
| `survey_received` | 5 |
| `neutral` | 6 |
| `event_rescheduled` | 7 |
| `unrelated` | 8 |
| `digest` | 9 |

---

## Stack

| Layer | Tech |
|-------|------|
| Label UI | Streamlit (port 8503, auto-increments on collision) |
| Benchmark | Python + HuggingFace Transformers |
| Email fetch | IMAP (multi-account, targeted date/sender/subject filter) |
| Data | JSONL (`data/email_label_queue.jsonl`, `data/email_score.jsonl`) |
| Config | `config/label_tool.yaml` (gitignored — see `.example`) |

Conda environments:
- `job-seeker` — label tool UI
- `job-seeker-classifiers` — benchmark harness (separate env for heavy deps)

---

## Running

```bash
./manage.sh start              # start label tool UI (port collision-safe from 8503)
./manage.sh stop               # stop
./manage.sh restart            # restart
./manage.sh status             # show running state and port
./manage.sh logs               # tail label tool log
./manage.sh open               # open in browser
```

Benchmark:
```bash
./manage.sh benchmark --list-models    # list available zero-shot models
./manage.sh score                      # score models against labeled JSONL
./manage.sh score --include-slow       # include large/slow models
./manage.sh compare --limit 30         # visual comparison on live IMAP emails
```

Dev:
```bash
./manage.sh test               # run pytest suite
```

---

## Data flow

```
IMAP accounts → fetch (targeted or wide) → email_label_queue.jsonl
→ label tool card UI → email_score.jsonl
→ benchmark harness → model rankings
→ best model → Peregrine classifier adapter
```

Targeted fetch: date range + sender/subject filter for pulling historical emails on specific senders or topics without flooding the queue.

Discard: removes an email from the queue without writing to the score file — for emails that don't belong in the training set.

---

## Classifier adapters

`app/classifier_adapters.py` provides a common interface for swapping classifier backends. Falls back to the label name when no `LABEL_DESCRIPTIONS` entry is configured for a label (RerankerAdapter).

---

## License

BSL 1.1 — internal tool, not user-facing.

© 2026 Circuit Forge LLC
