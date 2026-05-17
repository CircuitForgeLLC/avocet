<div align="center">
  <img src="docs/avocet-logo.svg" alt="Avocet" height="96" />

  # Avocet

  **Email classifier training tool — label, benchmark, fine-tune.**

  [![Status: Internal Beta](https://img.shields.io/badge/status-internal%20beta-blue)]()
  [![Version](https://img.shields.io/badge/version-0.5.0-green)](https://git.opensourcesolarpunk.com/Circuit-Forge/avocet/releases)
  [![License: BSL 1.1](https://img.shields.io/badge/license-BSL%201.1-orange)](LICENSE)
  [![Stack: Vue 3 + FastAPI](https://img.shields.io/badge/stack-Vue%203%20%2B%20FastAPI-brightgreen)]()
  [![CircuitForge](https://img.shields.io/badge/by-CircuitForge-black)](https://circuitforge.tech)
</div>

---

## What is Avocet?

Avocet is the internal data pipeline Circuit Forge uses to build, evaluate, and fine-tune email classifiers. It implements a three-stage workflow: human labelers review emails one at a time in a drag-to-bucket UI and produce a ground-truth dataset; the benchmark harness scores any number of HuggingFace zero-shot models against that dataset and produces a ranked comparison; and the fine-tune harness adapts the best-scoring base model to the labeled distribution. The output feeds directly into Peregrine's email classification layer. No LLM API key required for the label tool or benchmark — all inference runs locally via HuggingFace Transformers.

---

## Quick Start

```bash
git clone https://git.opensourcesolarpunk.com/Circuit-Forge/avocet.git
cd avocet

# Copy config template and fill in your IMAP credentials
cp config/label_tool.yaml.example config/label_tool.yaml

# Start the label tool (Vue SPA + FastAPI, port 8503)
./manage.sh start
./manage.sh open
```

---

## Features

- **Drag-to-bucket label UI** — ASMR-style card interface; drag emails into labeled buckets or discard without queuing noise into the training set
- **Targeted IMAP fetch** — pull emails by date range, sender, or subject filter across multiple accounts without flooding the queue
- **Email classifier benchmark** — score any HuggingFace zero-shot model against your labeled JSONL; side-by-side comparison on live IMAP emails
- **Planning benchmark** — evaluate LLMs on structured planning tasks; compare models head-to-head with verbose diff output
- **Writing style benchmark** — compare Ollama models on writing style coherence; scan local disk for existing outputs
- **Fine-tune harness** — HuggingFace Transformers fine-tuning from labeled ground truth; classifier adapter interface for swapping backends at runtime
- **Local inference first** — no API key required; GPU optional; designed to run on developer hardware
- **Hot-reload dev mode** — uvicorn `--reload` + Vite HMR (hot module replacement) for fast iteration on both API and UI

---

## CLI Reference

All operations go through `manage.sh`.

### Label Tool

```bash
./manage.sh start          # Build Vue SPA and start FastAPI on port 8503
./manage.sh stop           # Stop FastAPI server
./manage.sh restart        # Stop, rebuild, and restart
./manage.sh status         # Show running state and port
./manage.sh logs           # Tail the API log
./manage.sh open           # Open http://localhost:8503 in browser
./manage.sh dev            # Hot-reload: uvicorn --reload + Vite HMR
./manage.sh test           # Run pytest suite
```

### Email Classifier Benchmark

```bash
./manage.sh benchmark [args]       # Run benchmark_classifier.py
./manage.sh list-models            # List available zero-shot models
./manage.sh score                  # Score models against labeled JSONL
./manage.sh score --include-slow   # Include large/slow models
./manage.sh compare --limit 30     # Side-by-side comparison on live IMAP emails
```

### Planning Benchmark

```bash
./manage.sh plans-bench [args]              # Run benchmark_plans.py
./manage.sh plans-list                      # List available models
./manage.sh plans-run <model> [args]        # Run a single model (verbose)
./manage.sh plans-compare <m1> <m2> [...]   # Compare models side-by-side
```

### Writing Style Benchmark

```bash
./manage.sh style-bench [args]     # Run benchmark_style.py
./manage.sh style-list             # List available Ollama models
./manage.sh style-run [args]       # Run writing style benchmark
./manage.sh style-last             # Print most recent benchmark report
```

---

## Data Flow

```
IMAP accounts
  → fetch (targeted or wide)
  → email_label_queue.jsonl

email_label_queue.jsonl
  → label tool drag-to-bucket UI
  → email_score.jsonl (ground truth)

email_score.jsonl
  → benchmark harness
  → model rankings

best model
  → fine-tune harness
  → Peregrine classifier adapter
```

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

| Layer | Technology |
|-------|-----------|
| Label UI | Vue 3 SPA (Vite) |
| API | FastAPI + uvicorn (port 8503) |
| Benchmark | Python + HuggingFace Transformers |
| Email fetch | IMAP (multi-account, targeted date/sender/subject filter) |
| Data | JSONL (`data/email_label_queue.jsonl`, `data/email_score.jsonl`) |
| Runtime | SQLite |
| Config | `config/label_tool.yaml` (gitignored — `.example` committed) |

---

## Logo

The Avocet logo (`avocet_v1_poly.svg`) lives in the shared graphics repo. Copy it to `docs/avocet-logo.svg` to render correctly in this README.

---

## About

Avocet is internal CircuitForge infrastructure, open source as a reference implementation. It is not a user-facing product. The primary consumer is [Peregrine](https://git.opensourcesolarpunk.com/Circuit-Forge/peregrine), CircuitForge's job-search pipeline tool.

Docs: [docs.circuitforge.tech/avocet](https://docs.circuitforge.tech/avocet)

## Forgejo-primary

Avocet is developed and maintained on Forgejo at [git.opensourcesolarpunk.com/Circuit-Forge/avocet](https://git.opensourcesolarpunk.com/Circuit-Forge/avocet). GitHub and Codeberg are read-only mirrors.

---

## License

[Business Source License 1.1](LICENSE) — classifier training is an AI feature under the CircuitForge licensing model.

Free for personal non-commercial self-hosting. Commercial use or SaaS re-hosting requires a paid license. Converts to MIT after 4 years.

© 2026 Circuit Forge LLC — Privacy · Safety · Accessibility
