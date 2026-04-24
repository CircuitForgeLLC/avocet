#!/usr/bin/env python
"""
Writing style benchmark harness -- score local text-gen models for writing style match.

Runs each model against a set of test prompts, extracts style signals from the
outputs, compares them to a style corpus, and produces a ranked markdown table.

Usage:
    # List available ollama models
    conda run -n cf python scripts/benchmark_style.py --list-models

    # Run against all models with default test prompts
    conda run -n cf python scripts/benchmark_style.py --run

    # Run specific models only
    conda run -n cf python scripts/benchmark_style.py --run --models mistral:7b,llama3.1:8b

    # Use a custom corpus directory
    conda run -n cf python scripts/benchmark_style.py --run --samples data/style_corpus/

    # Print last results table
    conda run -n cf python scripts/benchmark_style.py --show-last
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

_ROOT = Path(__file__).parent.parent
_CORPUS_DIR = _ROOT / "data" / "style_corpus"
_RESULTS_DIR = _ROOT / "benchmark_results"
_OLLAMA_URL = "http://localhost:11434"
_CFORCH_URL = "http://localhost:7700"

# Subdirectories under --scan-disk root that may contain GGUFs
_SCAN_SUBDIRS = ["textgen/models", "llama.cpp/models", "cf-text/models", "vllm/models"]

# ── Filler phrases that should be absent from good style-match output ──────────
FILLER_PHRASES: list[str] = [
    "delve", "certainly", "absolutely", "i apologize", "i'd be happy to",
    "of course", "great question", "i understand", "let me know if",
    "feel free to", "it's important to note", "it's worth noting",
    "in conclusion", "to summarize", "in summary",
]

# ── Test prompts: (thread_title, thread_body, context_tag) ───────────────────
# These are representative threads that Magpie might reply to.
# Extend this list with real examples as the corpus grows.
TEST_PROMPTS: list[dict[str, str]] = [
    {
        "tag": "selfhosted_ai_fatigue",
        "thread_title": "Anyone else getting tired of re-explaining their setup every time an AI model forgets?",
        "thread_body": (
            "Every session I start over. My whole hardware setup, what tools I use, "
            "what I've already tried. It's exhausting. There has to be a better way."
        ),
    },
    {
        "tag": "privacy_local_llm",
        "thread_title": "What's the point of running local LLMs if the apps still phone home?",
        "thread_body": (
            "I went through all the trouble of setting up ollama and now I find out "
            "the frontend I'm using is sending telemetry. Kind of defeats the purpose."
        ),
    },
    {
        "tag": "solarpunk_tech",
        "thread_title": "What does solarpunk computing actually look like in practice?",
        "thread_body": (
            "I keep seeing the aesthetic but not a lot of concrete examples of "
            "people living it out with their tech choices. What does it mean day to day?"
        ),
    },
    {
        "tag": "nd_tools",
        "thread_title": "Tools that actually help with executive function vs ones that just add friction",
        "thread_body": (
            "I've tried a dozen productivity apps and most of them require more "
            "executive function to maintain than they save. What actually sticks for you?"
        ),
    },
    {
        "tag": "data_ownership",
        "thread_title": "Who actually owns your data when you use a 'free' AI tool?",
        "thread_body": (
            "Read the ToS on three different AI assistants today. In all three cases "
            "your inputs can be used for training, shared with partners, and retained "
            "indefinitely. At what point does 'free' just mean you're the product?"
        ),
    },
    {
        "tag": "digital_culture",
        "thread_title": "The internet used to feel like it belonged to everyone. What happened?",
        "thread_body": (
            "I grew up on forums, IRC, personal homepages. Now everything is a platform "
            "owned by someone trying to extract value from the community that built it. "
            "Is the fediverse / self-hosting movement actually reversing this or just "
            "a niche hobby?"
        ),
    },
]

GENERATION_PARAMS: dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 0.9,
    "num_predict": 300,
}

SYSTEM_PROMPT = (
    "You are a writing assistant. Your job is to write a Reddit reply that matches "
    "the voice, tone, and style of the provided samples exactly.\n\n"
    "Voice characteristics:\n"
    "- Casual engineer tone. Short punchy sentences.\n"
    "- No hype, no buzzwords, no em dashes, no semicolons.\n"
    "- Community-first perspective. Solarpunk values.\n"
    "- Direct and opinionated. No throat-clearing or filler.\n"
    "- When relevant, mention personal experience with real tools.\n\n"
    "Write ONLY the reply. No preamble, no 'Here is a reply:', no meta-commentary."
)


# ── Style signal extraction ───────────────────────────────────────────────────

@dataclass
class StyleSignals:
    """Quantitative style signals extracted from a text sample."""
    sentence_count: int = 0
    word_count: int = 0
    avg_sentence_length: float = 0.0
    em_dash_count: int = 0
    semicolon_count: int = 0
    filler_hits: list[str] = field(default_factory=list)
    question_ratio: float = 0.0        # fraction of sentences ending in '?'
    first_person_ratio: float = 0.0    # fraction of sentences starting with 'I'
    avg_word_length: float = 0.0


def extract_signals(text: str) -> StyleSignals:
    """Extract style signals from a text sample."""
    text = text.strip()
    if text.startswith("[ERROR:"):
        return StyleSignals()  # zero-score sentinel — caller checks for empty output
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    words = text.split()

    if not sentences:
        return StyleSignals()

    avg_sentence_length = len(words) / len(sentences) if sentences else 0.0
    avg_word_length = (sum(len(w.strip('.,!?;:"\'')) for w in words) / len(words)) if words else 0.0

    em_dash_count = text.count('\u2014') + text.count(' -- ') + text.count('--')
    semicolon_count = text.count(';')

    filler_hits = [p for p in FILLER_PHRASES if p.lower() in text.lower()]

    question_ratio = sum(1 for s in sentences if s.endswith('?')) / len(sentences)
    first_person_ratio = sum(1 for s in sentences if re.match(r"^I\b", s)) / len(sentences)

    return StyleSignals(
        sentence_count=len(sentences),
        word_count=len(words),
        avg_sentence_length=avg_sentence_length,
        em_dash_count=em_dash_count,
        semicolon_count=semicolon_count,
        filler_hits=filler_hits,
        question_ratio=question_ratio,
        first_person_ratio=first_person_ratio,
        avg_word_length=avg_word_length,
    )


def build_corpus_profile(corpus_dir: Path) -> StyleSignals | None:
    """Aggregate style signals across all corpus samples into a target profile."""
    samples = list(corpus_dir.glob("*.txt"))
    if not samples:
        return None

    all_signals = [extract_signals(p.read_text(encoding="utf-8")) for p in samples]
    n = len(all_signals)

    return StyleSignals(
        sentence_count=int(sum(s.sentence_count for s in all_signals) / n),
        word_count=int(sum(s.word_count for s in all_signals) / n),
        avg_sentence_length=sum(s.avg_sentence_length for s in all_signals) / n,
        em_dash_count=int(sum(s.em_dash_count for s in all_signals) / n),
        semicolon_count=int(sum(s.semicolon_count for s in all_signals) / n),
        question_ratio=sum(s.question_ratio for s in all_signals) / n,
        first_person_ratio=sum(s.first_person_ratio for s in all_signals) / n,
        avg_word_length=sum(s.avg_word_length for s in all_signals) / n,
    )


def score_against_profile(output_signals: StyleSignals, profile: StyleSignals | None) -> float:
    """Score a model output against the corpus profile. Returns 0-100.

    Penalties:
    - Em dashes / semicolons: -5 each occurrence (hard CF style violation)
    - Filler phrases: -8 each hit (strong signal of non-style output)
    - Sentence length delta: proportional penalty (target: close to corpus avg)
    - Word length delta: smaller penalty

    When no corpus profile is available, falls back to absolute signal scores only.
    """
    score = 100.0

    # Hard violations -- always penalised regardless of corpus
    score -= output_signals.em_dash_count * 5
    score -= output_signals.semicolon_count * 3
    score -= len(output_signals.filler_hits) * 8

    if profile is not None:
        # Sentence length delta: penalise proportionally
        length_delta = abs(output_signals.avg_sentence_length - profile.avg_sentence_length)
        score -= min(length_delta * 2, 20)

        # Question ratio delta
        question_delta = abs(output_signals.question_ratio - profile.question_ratio)
        score -= min(question_delta * 10, 10)

    return max(0.0, score)


# ── Ollama generation ─────────────────────────────────────────────────────────

_CFORCH_NODE_ID = "heimdall"


def cforch_list_catalog(
    cforch_url: str = _CFORCH_URL,
    node_id: str = _CFORCH_NODE_ID,
) -> dict[str, int]:
    """Return the cf-text catalog from cf-orch as {model_id: vram_mb}.

    Uses ?node_id= to request the catalog from a specific node's profile,
    avoiding cross-node catalog shadowing when multiple nodes define catalogs
    for the same service.
    """
    try:
        resp = httpx.get(
            f"{cforch_url}/api/services/cf-text/catalog",
            params={"node_id": node_id} if node_id else {},
            timeout=10.0,
        )
        resp.raise_for_status()
        raw = resp.json()
        return {
            model_id: (entry.get("vram_mb", 0) if isinstance(entry, dict) else 0)
            for model_id, entry in raw.items()
        }
    except Exception as exc:
        print(f"[warn] Could not reach cf-orch catalog at {cforch_url}: {exc}", file=sys.stderr)
        return {}


def _cforch_allocate_service(
    service: str,
    model_id: str,
    cforch_url: str,
    startup_timeout_s: float,
    health_path: str,
) -> tuple[str, str] | None:
    """Generic cf-orch allocate + state-signal wait. Returns (service_url, allocation_id) or None.

    After allocating, waits for the coordinator's service state to reach 'running'.
    Fails immediately if the state reaches 'stopped' (crashed load) — no waiting out
    the full timeout for a model that already failed.
    Falls back to health-polling if the coordinator doesn't expose a matching instance
    (e.g. older coordinator version or service not yet registered in probe loop).
    """
    try:
        resp = httpx.post(
            f"{cforch_url}/api/services/{service}/allocate",
            json={
                "model_candidates": [model_id],
                "caller": "avocet",
                "pipeline": "style_benchmark",
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        service_url: str = data["url"]
        allocation_id: str = data.get("allocation_id", "")
        node_id: str = data.get("node_id", "")
        gpu_id: int | None = data.get("gpu_id")

        if data.get("started", False) and not data.get("warm", True):
            print(f"  [cold start] waiting for {service} to load {model_id!r}...", end=" ", flush=True)
            t0 = time.monotonic()
            deadline = t0 + startup_timeout_s
            probe_misses = 0  # consecutive polls with no matching instance in status

            while time.monotonic() < deadline:
                try:
                    status = httpx.get(
                        f"{cforch_url}/api/services/{service}/status", timeout=5.0
                    )
                    if status.is_success:
                        instances = status.json().get("instances", [])
                        # Find our specific instance by node+gpu
                        match = next(
                            (i for i in instances
                             if i.get("node_id") == node_id and i.get("gpu_id") == gpu_id),
                            None,
                        )
                        if match:
                            probe_misses = 0
                            state = match.get("state", "")
                            if state == "running":
                                elapsed = time.monotonic() - t0
                                print(f"ready ({elapsed:.0f}s)", flush=True)
                                return service_url, allocation_id
                            elif state == "stopped":
                                print(f"failed (service stopped — model load error)", flush=True)
                                return None
                            # state == "starting" or unknown → keep waiting
                        else:
                            probe_misses += 1
                            # After a grace period with no instance visible, fall back to
                            # direct health-poll (coordinator may not have probed yet)
                            if probe_misses >= 6:
                                try:
                                    health = httpx.get(f"{service_url}{health_path}", timeout=3.0)
                                    if health.is_success:
                                        elapsed = time.monotonic() - t0
                                        print(f"ready via health ({elapsed:.0f}s)", flush=True)
                                        return service_url, allocation_id
                                except Exception:
                                    pass
                except Exception:
                    pass
                time.sleep(3.0)

            elapsed = time.monotonic() - t0
            print(f"timed out after {elapsed:.0f}s", flush=True)
            return None

        return service_url, allocation_id
    except Exception as exc:
        print(f"[warn] cf-orch allocation failed for {model_id!r} ({service}): {exc}", file=sys.stderr)
        return None


def cforch_allocate(
    model_id: str,
    cforch_url: str = _CFORCH_URL,
    startup_timeout_s: float = 180.0,
) -> tuple[str, str] | None:
    """Allocate a cf-text instance for model_id. Returns (service_url, allocation_id) or None."""
    return _cforch_allocate_service("cf-text", model_id, cforch_url, startup_timeout_s, "/health")


def cforch_allocate_vllm(
    model_id: str,
    cforch_url: str = _CFORCH_URL,
    startup_timeout_s: float = 300.0,
) -> tuple[str, str] | None:
    """Allocate a vllm instance for model_id. Returns (service_url, allocation_id) or None.

    vllm exposes an OpenAI-compatible API — generate_cftext() works unchanged
    against the returned service_url.  Startup timeout is longer (300s) because
    vllm loads large model weights from disk before becoming ready.
    """
    return _cforch_allocate_service("vllm", model_id, cforch_url, startup_timeout_s, "/health")


def cforch_release(allocation_id: str, cforch_url: str = _CFORCH_URL) -> None:
    """Release a cf-orch allocation."""
    if not allocation_id:
        return
    try:
        httpx.delete(f"{cforch_url}/api/services/cf-text/allocations/{allocation_id}", timeout=10.0)
    except Exception:
        pass


def generate_cftext(
    service_url: str,
    model_id: str,
    prompt: str,
    system: str = "",
) -> tuple[str, float]:
    """Call cf-text via OpenAI-compatible /v1/chat/completions. Returns (text, elapsed_ms)."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": GENERATION_PARAMS.get("num_predict", 300),
        "temperature": GENERATION_PARAMS.get("temperature", 0.7),
        "top_p": GENERATION_PARAMS.get("top_p", 0.9),
        "stream": False,
    }

    t0 = time.monotonic()
    try:
        resp = httpx.post(
            f"{service_url.rstrip('/')}/v1/chat/completions",
            json=payload,
            timeout=180.0,
        )
        resp.raise_for_status()
        elapsed_ms = (time.monotonic() - t0) * 1000
        content = resp.json()["choices"][0]["message"]["content"]
        return content.strip(), elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        return f"[ERROR: {exc}]", elapsed_ms


def generate(model_id: str, prompt: str, system: str = "") -> tuple[str, float]:
    """Call ollama /api/generate. Returns (text, elapsed_ms)."""
    payload: dict[str, Any] = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": GENERATION_PARAMS,
    }
    if system:
        payload["system"] = system

    t0 = time.monotonic()
    try:
        resp = httpx.post(
            f"{_OLLAMA_URL}/api/generate",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        elapsed_ms = (time.monotonic() - t0) * 1000
        return resp.json().get("response", "").strip(), elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        return f"[ERROR: {exc}]", elapsed_ms


def find_disk_ggufs(llm_root: Path) -> list[Path]:
    """Recursively find .gguf files under known subdirs of llm_root.

    Skips vocab-only GGUFs (ggml-vocab-*) which aren't standalone models.
    """
    found: list[Path] = []
    search_dirs = [llm_root / sub for sub in _SCAN_SUBDIRS] + [llm_root]
    seen: set[Path] = set()
    for base in search_dirs:
        if not base.exists():
            continue
        for gguf in base.rglob("*.gguf"):
            if gguf in seen:
                continue
            seen.add(gguf)
            if gguf.name.startswith("ggml-vocab-"):
                continue
            found.append(gguf)
    return sorted(found)


def gguf_to_ollama_tag(gguf_path: Path) -> str:
    """Derive a stable ollama tag from a GGUF path.

    Uses parent dir name + stem to avoid collisions, e.g.:
    claude-3.7-sonnet-reasoning-gemma3-12B/foo.Q8_0.gguf
    → bench-claude-3.7-sonnet-reasoning-gemma3-12b-foo-q8-0
    """
    parent = gguf_path.parent.name.lower()
    stem = gguf_path.stem.lower()
    # If stem is contained in parent (common pattern), just use parent
    slug = parent if stem.replace("-", "").replace("_", "") in parent.replace("-", "").replace("_", "") else f"{parent}-{stem}"
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"bench-{slug}:latest"


def register_gguf(gguf_path: Path, tag: str) -> bool:
    """Create a temporary ollama model entry from a GGUF file. Returns True on success."""
    import subprocess
    import tempfile
    modelfile = f"FROM {gguf_path.resolve()}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".Modelfile", delete=False) as f:
        f.write(modelfile)
        modelfile_path = f.name
    try:
        result = subprocess.run(
            ["ollama", "create", tag, "-f", modelfile_path],
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0
    except Exception as exc:
        print(f"[warn] Could not register {gguf_path.name}: {exc}", file=sys.stderr)
        return False
    finally:
        Path(modelfile_path).unlink(missing_ok=True)


def deregister_gguf(tag: str) -> None:
    """Remove a temporary ollama model entry."""
    import subprocess
    try:
        subprocess.run(["ollama", "rm", tag], capture_output=True, timeout=30)
    except Exception:
        pass


def backfill_disk_models(
    llm_root: Path,
    existing_tags: set[str],
    max_vram_mb: int = 0,
) -> list[str]:
    """Register GGUFs from disk that aren't already in ollama. Returns new tags.

    max_vram_mb: skip files whose size exceeds this threshold (0 = no limit).
    GGUF file size is a reliable VRAM proxy -- quantized weights load ~1:1.
    """
    ggufs = find_disk_ggufs(llm_root)
    if not ggufs:
        print(f"No .gguf files found under {llm_root}", file=sys.stderr)
        return []

    new_tags: list[str] = []
    skipped_oom = 0
    for gguf in ggufs:
        size_mb = gguf.stat().st_size // (1024 * 1024)
        if max_vram_mb and size_mb > max_vram_mb:
            print(f"  [skip-oom] {gguf.name}  ({size_mb} MB > {max_vram_mb} MB limit)")
            skipped_oom += 1
            continue
        tag = gguf_to_ollama_tag(gguf)
        if tag in existing_tags:
            print(f"  [skip] {gguf.name} already registered as {tag}")
            continue
        print(f"  [register] {gguf.name} ({size_mb} MB) → {tag} ...", end=" ", flush=True)
        if register_gguf(gguf, tag):
            print("ok")
            new_tags.append(tag)
        else:
            print("failed")

    if skipped_oom:
        print(f"  [info] {skipped_oom} GGUF(s) skipped (exceed {max_vram_mb} MB VRAM limit)")
    return new_tags


def list_ollama_models() -> list[str]:
    """Return model names from ollama /api/tags, filtered to text-gen candidates."""
    try:
        resp = httpx.get(f"{_OLLAMA_URL}/api/tags", timeout=10.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        # Exclude embedding-only models
        exclude = {"mxbai-embed-large", "nomic-embed-text", "all-minilm"}
        return [
            m["name"] for m in models
            if not any(x in m["name"].lower() for x in exclude)
        ]
    except Exception as exc:
        print(f"[warn] Could not reach ollama: {exc}", file=sys.stderr)
        return []


# ── Run benchmark ─────────────────────────────────────────────────────────────

@dataclass
class ModelResult:
    model_id: str
    prompt_results: list[dict[str, Any]] = field(default_factory=list)
    avg_score: float = 0.0
    avg_latency_ms: float = 0.0
    total_filler_hits: int = 0
    total_em_dashes: int = 0
    total_semicolons: int = 0


def _bench_one_model(
    model_id: str,
    prompts: list[dict[str, str]],
    profile: Any,
    use_cforch: bool,
    cforch_url: str,
    use_vllm: bool = False,
) -> "ModelResult | None":
    """Run all prompts for a single model. Thread-safe — all output is prefixed with model_id.

    Dispatch priority:
      use_vllm=True  → allocate vllm via cf-orch, then generate_cftext() (OpenAI-compatible)
      use_cforch=True → allocate cf-text via cf-orch, then generate_cftext()
      else           → direct ollama generate()
    Both vllm and cf-text expose /v1/chat/completions so generate_cftext() works for both.
    """
    prefix = f"[{model_id}]"
    result = ModelResult(model_id=model_id)

    service_url: str | None = None
    allocation_id: str = ""
    if use_vllm:
        alloc = cforch_allocate_vllm(model_id, cforch_url)
        if alloc is None:
            print(f"{prefix} [skip] vllm allocation failed", flush=True)
            return None
        service_url, allocation_id = alloc
        print(f"{prefix} vllm allocated: {service_url}", flush=True)
    elif use_cforch:
        alloc = cforch_allocate(model_id, cforch_url)
        if alloc is None:
            print(f"{prefix} [skip] cf-orch allocation failed", flush=True)
            return None
        service_url, allocation_id = alloc
        print(f"{prefix} allocated: {service_url}", flush=True)

    try:
        for prompt_def in prompts:
            tag = prompt_def["tag"]
            user_prompt = (
                f"Thread: {prompt_def['thread_title']}\n\n"
                f"{prompt_def['thread_body']}\n\n"
                f"Write a reply:"
            )
            print(f"{prefix} [{tag}] generating...", flush=True)

            if (use_cforch or use_vllm) and service_url:
                # Both cf-text and vllm expose /v1/chat/completions — same call
                output, elapsed_ms = generate_cftext(service_url, model_id, user_prompt, system=SYSTEM_PROMPT)
            else:
                output, elapsed_ms = generate(model_id, user_prompt, system=SYSTEM_PROMPT)

            signals = extract_signals(output)
            score = score_against_profile(signals, profile)

            print(f"{prefix} [{tag}] {score:.0f}/100  ({elapsed_ms:.0f}ms)", flush=True)
            if signals.filler_hits:
                print(f"{prefix}   ⚠ filler: {signals.filler_hits}", flush=True)
            if signals.em_dash_count:
                print(f"{prefix}   ⚠ em-dashes: {signals.em_dash_count}", flush=True)

            result.prompt_results.append({
                "tag": tag,
                "user_prompt": user_prompt,
                "output": output,
                "signals": {
                    "avg_sentence_length": signals.avg_sentence_length,
                    "em_dash_count": signals.em_dash_count,
                    "semicolon_count": signals.semicolon_count,
                    "filler_hits": signals.filler_hits,
                    "question_ratio": signals.question_ratio,
                    "word_count": signals.word_count,
                },
                "score": score,
                "latency_ms": elapsed_ms,
            })
    finally:
        if (use_cforch or use_vllm) and allocation_id:
            cforch_release(allocation_id, cforch_url)

    if not result.prompt_results:
        return None

    scores    = [r["score"]      for r in result.prompt_results]
    latencies = [r["latency_ms"] for r in result.prompt_results]
    result.avg_score       = sum(scores) / len(scores)
    result.avg_latency_ms  = sum(latencies) / len(latencies)
    result.total_filler_hits = sum(len(r["signals"]["filler_hits"]) for r in result.prompt_results)
    result.total_em_dashes   = sum(r["signals"]["em_dash_count"]    for r in result.prompt_results)
    result.total_semicolons  = sum(r["signals"]["semicolon_count"]  for r in result.prompt_results)

    print(f"{prefix} done — avg score {result.avg_score:.0f}/100", flush=True)
    return result


def run_benchmark(
    model_ids: list[str],
    corpus_dir: Path,
    prompts: list[dict[str, str]],
    use_cforch: bool = False,
    use_vllm: bool = False,
    cforch_url: str = _CFORCH_URL,
    workers: int = 1,
) -> list[ModelResult]:
    profile = build_corpus_profile(corpus_dir)
    if profile:
        print(f"Corpus profile loaded from {corpus_dir} ({len(list(corpus_dir.glob('*.txt')))} samples)")
        print(f"  Target avg sentence length: {profile.avg_sentence_length:.1f} words")
    else:
        print(f"[warn] No corpus samples found in {corpus_dir} -- scoring on hard violations only")

    backend = "vllm via cf-orch" if use_vllm else ("cf-text via cf-orch" if use_cforch else "ollama")
    print(f"  Backend: {backend}")

    effective_workers = min(workers, len(model_ids)) if model_ids else 1
    print(f"  Workers: {effective_workers} (of {len(model_ids)} models)", flush=True)

    results: list[ModelResult] = []

    if effective_workers <= 1:
        # Sequential path — simpler output, easier to follow for single-model runs
        for model_id in model_ids:
            print(f"\n{'='*60}\nModel: {model_id}", flush=True)
            r = _bench_one_model(model_id, prompts, profile, use_cforch, cforch_url, use_vllm)
            if r:
                results.append(r)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print(f"  Fanning out {len(model_ids)} models across {effective_workers} workers...", flush=True)
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = {
                pool.submit(_bench_one_model, mid, prompts, profile, use_cforch, cforch_url, use_vllm): mid
                for mid in model_ids
            }
            for future in as_completed(futures):
                r = future.result()
                if r:
                    results.append(r)

    return sorted(results, key=lambda r: r.avg_score, reverse=True)


# ── Markdown report ───────────────────────────────────────────────────────────

def render_report(results: list[ModelResult], corpus_dir: Path) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        f"# Writing Style Benchmark Results",
        f"",
        f"**Date:** {date_str}  ",
        f"**Corpus:** `{corpus_dir}`  ",
        f"**Models tested:** {len(results)}  ",
        f"**Prompts per model:** {len(TEST_PROMPTS)}",
        f"",
        f"## Rankings",
        f"",
        f"| Rank | Model | Score | Latency | Em-dashes | Fillers | Semicolons |",
        f"|------|-------|-------|---------|-----------|---------|------------|",
    ]

    for i, r in enumerate(results, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
        lines.append(
            f"| {medal} | `{r.model_id}` | {r.avg_score:.0f}/100 "
            f"| {r.avg_latency_ms:.0f}ms "
            f"| {r.total_em_dashes} "
            f"| {r.total_filler_hits} "
            f"| {r.total_semicolons} |"
        )

    lines += ["", "## Sample Outputs", ""]

    for r in results[:3]:  # top 3 only to keep report readable
        lines += [f"### `{r.model_id}` (avg score: {r.avg_score:.0f})", ""]
        for pr in r.prompt_results:
            lines += [
                f"**Prompt:** {pr['tag']}  ",
                f"**Score:** {pr['score']:.0f}/100  ",
                f"",
                f"```",
                pr["output"],
                f"```",
                f"",
            ]

    return "\n".join(lines)


def save_report(results: list[ModelResult], corpus_dir: Path) -> Path:
    _RESULTS_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    report_path = _RESULTS_DIR / f"style_{date_str}.md"
    report_path.write_text(render_report(results, corpus_dir), encoding="utf-8")

    # Also save raw JSON for programmatic use
    json_path = _RESULTS_DIR / f"style_{date_str}.json"
    json_path.write_text(
        json.dumps(
            [
                {
                    "model_id": r.model_id,
                    "avg_score": r.avg_score,
                    "avg_latency_ms": r.avg_latency_ms,
                    "total_filler_hits": r.total_filler_hits,
                    "total_em_dashes": r.total_em_dashes,
                    "total_semicolons": r.total_semicolons,
                    "prompt_results": r.prompt_results,
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    return report_path


# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_list_models(_args: argparse.Namespace) -> None:
    models = list_ollama_models()
    if not models:
        print("No models found (is ollama running?)")
        return
    print(f"{len(models)} models available:\n")
    for m in models:
        print(f"  {m}")


def cmd_run(args: argparse.Namespace) -> None:
    corpus_dir = Path(args.samples)
    if not corpus_dir.exists():
        print(f"[error] Corpus directory not found: {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    max_vram_mb: int = getattr(args, "max_vram", 7200)
    use_cforch: bool = getattr(args, "cforch", False)
    use_vllm:   bool = getattr(args, "vllm", False)
    cforch_url: str = getattr(args, "cforch_url", _CFORCH_URL)
    registered_tags: list[str] = []

    def _filter_ollama_by_size(ids: list[str], include_large: bool) -> list[str]:
        """Apply name-pattern size filter to ollama model list."""
        if include_large:
            return ids
        skip_patterns = ["270b", "70b", "32b", "30b", "21b", "20b", "deepseek-r1"]
        filtered = [m for m in ids if not any(p in m.lower() for p in skip_patterns)]
        skipped = len(ids) - len(filtered)
        if skipped:
            print(f"[info] Skipped {skipped} large model(s) by name pattern. "
                  "Pass --include-large to include them.")
        return filtered

    if args.models and args.models != "all":
        model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    elif use_cforch:
        # cf-orch path: pull model list from catalog, filter by vram_mb
        catalog = cforch_list_catalog(cforch_url)
        if not catalog:
            print("[warn] cf-orch catalog empty or unreachable -- falling back to ollama models")
            use_cforch = False
            model_ids = _filter_ollama_by_size(list_ollama_models(), args.include_large)
            if not model_ids:
                print("[error] No models found. Pass --models explicitly or check ollama.", file=sys.stderr)
                sys.exit(1)
        else:
            before = list(catalog.items())
            allowed = {mid: mb for mid, mb in before if mb == 0 or mb <= max_vram_mb}
            skipped_oom = {mid: mb for mid, mb in before if mid not in allowed}
            model_ids = list(allowed.keys())
            print(f"[info] cf-orch catalog: {len(before)} model(s), "
                  f"{len(allowed)} within {max_vram_mb} MB VRAM limit")
            if skipped_oom:
                print(f"[info] Skipped (OOM risk): "
                      + ", ".join(f"{mid} ({mb} MB)" for mid, mb in sorted(skipped_oom.items())))
    else:
        # Ollama path
        model_ids = list_ollama_models()
        if not model_ids:
            print("[error] No models found. Pass --models explicitly or check ollama.", file=sys.stderr)
            sys.exit(1)

        # Backfill GGUFs from disk before filtering -- skips files that exceed VRAM limit
        if getattr(args, "scan_disk", None):
            llm_root = Path(args.scan_disk)
            print(f"\nScanning {llm_root} for unregistered GGUFs (limit: {max_vram_mb} MB)...")
            registered_tags = backfill_disk_models(llm_root, set(model_ids), max_vram_mb=max_vram_mb)
            model_ids = list_ollama_models()  # re-fetch with new registrations

        model_ids = _filter_ollama_by_size(model_ids, args.include_large)

    print(f"\nRunning writing style benchmark on {len(model_ids)} model(s)...")
    try:
        results = run_benchmark(model_ids, corpus_dir, TEST_PROMPTS, use_cforch=use_cforch, use_vllm=use_vllm, cforch_url=cforch_url, workers=args.workers)
        report_path = save_report(results, corpus_dir)
        print(f"\n{'='*60}")
        print(f"Results saved to: {report_path}")
        print(f"\n{render_report(results, corpus_dir)}")
    finally:
        if registered_tags:
            print(f"\nCleaning up {len(registered_tags)} temporary ollama registrations...")
            for tag in registered_tags:
                deregister_gguf(tag)


def cmd_show_last(_args: argparse.Namespace) -> None:
    reports = sorted(_RESULTS_DIR.glob("style_*.md"), reverse=True)
    if not reports:
        print("No benchmark results found. Run --run first.")
        return
    print(reports[0].read_text(encoding="utf-8"))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Writing style benchmark harness for local text-gen models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list-models", help="List available ollama models")

    run_p = sub.add_parser("run", help="Run the benchmark")
    run_p.add_argument("--models", default="all", help="Comma-separated model IDs, or 'all'")
    run_p.add_argument("--samples", default=str(_CORPUS_DIR), help="Path to style corpus directory")
    run_p.add_argument("--include-large", action="store_true", help="Include models >20B params")
    run_p.add_argument("--scan-disk", metavar="LLM_ROOT", help="Scan directory for GGUFs not yet in ollama (e.g. /Library/Assets/LLM)")
    run_p.add_argument("--cforch", action="store_true", help="Route generation through cf-orch/cf-text instead of direct ollama")
    run_p.add_argument("--vllm", action="store_true", help="Route generation through cf-orch/vllm (OpenAI-compatible) instead of ollama")
    run_p.add_argument("--cforch-url", default=_CFORCH_URL, help=f"cf-orch coordinator URL (default: {_CFORCH_URL})")
    run_p.add_argument("--max-vram", type=int, default=7200, metavar="MB",
                       help="Skip models whose VRAM footprint exceeds this limit in MB (default: 7200)")
    run_p.add_argument("--workers", type=int, default=1, metavar="N",
                       help="Parallel workers — run N models simultaneously (default: 1; use 4+ with cf-orch)")

    sub.add_parser("show-last", help="Print the most recent benchmark report")

    # Also support legacy --list-models / --run / --show-last flags for manage.sh compat
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--show-last", action="store_true")
    parser.add_argument("--models", default="all")
    parser.add_argument("--samples", default=str(_CORPUS_DIR))
    parser.add_argument("--include-large", action="store_true")
    parser.add_argument("--scan-disk", metavar="LLM_ROOT")
    parser.add_argument("--cforch", action="store_true")
    parser.add_argument("--vllm", action="store_true")
    parser.add_argument("--cforch-url", default=_CFORCH_URL)
    parser.add_argument("--max-vram", type=int, default=7200, metavar="MB")
    parser.add_argument("--workers", type=int, default=1, metavar="N")

    args = parser.parse_args()

    if args.cmd == "list-models" or args.list_models:
        cmd_list_models(args)
    elif args.cmd == "run" or args.run:
        cmd_run(args)
    elif args.cmd == "show-last" or args.show_last:
        cmd_show_last(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
