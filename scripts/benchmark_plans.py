#!/usr/bin/env python
"""CF-specific planning benchmark — compare base models before fine-tuning.

Sends held-out CircuitForge planning prompts to one or more models via the
cf-text (local) or cf-orch API, then scores responses against CF-specific
rubrics. Use this to select the best base model for SFT.

Scoring rubrics (each 0-1, summed to total/N):
  - task_structure    : uses checkbox syntax (- [ ]), git commit steps
  - tier_awareness    : mentions Free/Paid/Premium/Ultra tiers
  - privacy_pillar    : mentions privacy/local-inference/no-logging
  - safety_pillar     : mentions safety, human approval, or reversibility
  - accessibility     : mentions ND/accessibility/adaptive needs
  - license_split     : mentions MIT vs BSL or open-core model
  - file_paths        : uses plausible file path references
  - cf_conventions    : uses conda run -n cf, /Library/Development/, or known CF dirs
  - paired_coherence  : (paired only) plan references the design doc's feature name
  - length_ok         : 300–2500 words (under-short = hallucination risk; over-long = padding)

Usage
-----
    # List available model targets
    python scripts/benchmark_plans.py --list-models

    # Run all held-out prompts against a single model, print report
    python scripts/benchmark_plans.py --model llama3.2-3b

    # Compare two models side-by-side
    python scripts/benchmark_plans.py --compare llama3.2-3b mistral-7b

    # Run with a custom API base (cf-text default: http://localhost:8080/v1)
    python scripts/benchmark_plans.py --model llama3.2-3b --api-base http://localhost:8080/v1

    # Export detailed results JSON
    python scripts/benchmark_plans.py --model llama3.2-3b --output data/bench_results.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import httpx

# ── Paths ──────────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent
_DATA_DIR = _ROOT / "data"

CF_TEXT_BASE   = "http://localhost:8080/v1"
CF_ORCH_BASE   = "http://localhost:8090/v1"
CF_COORD_URL   = "http://10.1.10.71:7700"   # cf-orch coordinator (LAN)

# ── Held-out prompts ───────────────────────────────────────────────────────────
# These are NOT in the training export (no matching docs in circuitforge-plans/).
# Each prompt exercises a different CF planning domain.

HELD_OUT_PROMPTS: list[dict[str, Any]] = [
    {
        "id": "ho_001",
        "name": "kiwi_barcode_ocr",
        "domain": "feature_plan",
        "prompt": (
            "You are a senior engineer on Kiwi, a CircuitForge pantry-tracking product. "
            "Write a detailed implementation plan for adding barcode scanning via device camera "
            "and receipt OCR to the item-add flow.\n\n"
            "The plan should include: file structure (create/modify), step-by-step task checklist "
            "with checkboxes, any DB migrations, and git commit steps."
        ),
        "expected_signals": ["task_structure", "file_paths", "cf_conventions"],
    },
    {
        "id": "ho_002",
        "name": "peregrine_ats_scoring",
        "domain": "feature_design",
        "prompt": (
            "Write a design document for Peregrine: ATS keyword scoring for job applications.\n\n"
            "Context: Peregrine users paste job descriptions and their resume. "
            "We want to score how well the resume keywords match the JD and suggest rewrites. "
            "Describe the architecture, data flow, and key design decisions."
        ),
        "expected_signals": ["privacy_pillar", "tier_awareness", "license_split"],
    },
    {
        "id": "ho_003",
        "name": "tier_gate_local_llm",
        "domain": "architecture",
        "prompt": (
            "Design the tier-gating architecture for a new CircuitForge product. "
            "The product should:\n"
            "- Default to local LLM inference for all tiers\n"
            "- Unlock cloud LLM for Paid tier and above\n"
            "- Keep fine-tuned model weights for Premium/Ultra only\n\n"
            "Describe how the tier check integrates with the LLM router, "
            "what happens when a Free user tries a Paid-tier feature, "
            "and how BYOK (bring-your-own-key) fits in."
        ),
        "expected_signals": ["tier_awareness", "privacy_pillar", "license_split"],
    },
    {
        "id": "ho_004",
        "name": "heimdall_webhook_plan",
        "domain": "feature_plan",
        "prompt": (
            "Break the following Heimdall feature into a detailed implementation plan with "
            "file structure and task checkboxes — Stripe webhook handler for subscription lifecycle.\n\n"
            "Heimdall is the CircuitForge license server (FastAPI + SQLite). "
            "The webhook needs to handle checkout.session.completed, "
            "customer.subscription.updated, and customer.subscription.deleted events."
        ),
        "expected_signals": ["task_structure", "file_paths", "safety_pillar"],
    },
    {
        "id": "ho_005",
        "name": "nd_accessible_onboarding",
        "domain": "ux_design",
        "prompt": (
            "You are a product designer working on Harrier, a CircuitForge tool for "
            "helping people navigate government benefits applications.\n\n"
            "Design the onboarding flow for neurodivergent (ND) users. "
            "Consider: ADHD time-blindness, executive function challenges, demand avoidance, "
            "and rejection sensitivity. The flow should reduce cognitive load and "
            "never use urgency or panic patterns."
        ),
        "expected_signals": ["accessibility", "safety_pillar", "privacy_pillar"],
    },
    {
        "id": "ho_006",
        "name": "circuitforge_core_extraction",
        "domain": "architecture",
        "prompt": (
            "Produce a CircuitForge-style design document for the following circuitforge-core "
            "feature — shared ActivityPub federation module.\n\n"
            "Background: Multiple CF products (Kiwi, Rook, Snipe) want to publish updates "
            "to ActivityPub. Build it once in cf-core (MIT licensed) so all products can use it. "
            "Design the module API, describe what belongs in MIT vs BSL, and note federation "
            "privacy constraints."
        ),
        "expected_signals": ["license_split", "privacy_pillar", "cf_conventions"],
    },
    {
        "id": "ho_007",
        "name": "snipe_trust_score_plan",
        "domain": "feature_plan",
        "prompt": (
            "You are a senior engineer on Snipe, a CircuitForge eBay trust-scoring tool. "
            "Write a step-by-step engineering plan for: seller trust score calculation.\n\n"
            "The score should combine: feedback ratio, account age, item-specifics completeness, "
            "listing photo quality, and shipping time accuracy. "
            "Include file structure, test plan, and migration steps."
        ),
        "expected_signals": ["task_structure", "file_paths", "safety_pillar"],
    },
    {
        "id": "ho_008",
        "name": "avocet_training_pipeline",
        "domain": "feature_plan",
        "prompt": (
            "Break the following Avocet feature into a detailed implementation plan — "
            "end-to-end fine-tuning pipeline from labeled JSONL to deployed GGUF model.\n\n"
            "Avocet is the CircuitForge email classifier training tool. "
            "The pipeline should: validate the dataset, run LoRA SFT via unsloth, "
            "quantize to Q5_K_M GGUF, run the benchmark harness, and register the model "
            "in the Avocet model queue if it beats the baseline."
        ),
        "expected_signals": ["task_structure", "file_paths", "cf_conventions"],
    },
    {
        "id": "ho_009",
        "name": "privacy_data_flow",
        "domain": "architecture",
        "prompt": (
            "Design the data privacy architecture for a CircuitForge cloud product. "
            "Describe: what PII is collected, how it's stored, retention policy, "
            "obfuscation strategy for cloud-side logs, and how consent is obtained "
            "in plain language. The product handles job applications (resumes, cover letters)."
        ),
        "expected_signals": ["privacy_pillar", "safety_pillar", "accessibility"],
    },
    {
        "id": "ho_010",
        "name": "git_workflow_doc",
        "domain": "process_doc",
        "prompt": (
            "Write a developer process document for CircuitForge: conventional commit and "
            "branch workflow for a BSL 1.1 open-core product.\n\n"
            "Cover: commit message format (type: description), branch naming, "
            "when to use feature branches vs direct main commits, "
            "how the MIT/BSL split affects which commits go in which branch, "
            "and how CI gates on gitleaks for secret scanning."
        ),
        "expected_signals": ["license_split", "cf_conventions", "task_structure"],
    },
]

# ── Rubric scoring ─────────────────────────────────────────────────────────────

_TASK_STRUCTURE_RE = re.compile(r"- \[ \]", re.MULTILINE)
_COMMIT_RE = re.compile(r"git commit|git add", re.IGNORECASE)
_TIER_RE = re.compile(r"\b(Free|Paid|Premium|Ultra)\s+tier|\btier\s+(Free|Paid|Premium|Ultra)", re.IGNORECASE)
_PRIVACY_RE = re.compile(r"\b(privacy|local.?inference|no.?logging|no.?pii|user.?data|data.?reten|obfuscat)", re.IGNORECASE)
_SAFETY_RE = re.compile(r"\b(human.?approv|reversib|safety|safe.?default|fail.?safe|harm)", re.IGNORECASE)
_A11Y_RE = re.compile(r"\b(neurodiverg|ND\b|accessib|adaptive|ADHD|autism|executive.?function|demand.?avoid)", re.IGNORECASE)
_LICENSE_RE = re.compile(r"\b(MIT|BSL|open.?core|proprietary|commercial.?licens)", re.IGNORECASE)
_FILE_PATH_RE = re.compile(r"(app/|tests?/|src/|scripts?/)\w[\w/.-]{3,}", re.IGNORECASE)
_CF_CONV_RE = re.compile(r"(conda run -n cf|/Library/Development/CircuitForge|circuitforge-core|manage\.sh)", re.IGNORECASE)


@dataclass
class RubricScore:
    task_structure: float = 0.0
    tier_awareness: float = 0.0
    privacy_pillar: float = 0.0
    safety_pillar: float = 0.0
    accessibility: float = 0.0
    license_split: float = 0.0
    file_paths: float = 0.0
    cf_conventions: float = 0.0
    length_ok: float = 0.0

    def total(self) -> float:
        vals = [self.task_structure, self.tier_awareness, self.privacy_pillar,
                self.safety_pillar, self.accessibility, self.license_split,
                self.file_paths, self.cf_conventions, self.length_ok]
        return sum(vals) / len(vals)

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def score_response(response: str, prompt_meta: dict[str, Any]) -> RubricScore:
    words = len(response.split())
    s = RubricScore()

    # Task structure: needs checkboxes AND at least one commit step
    checkbox_hits = len(_TASK_STRUCTURE_RE.findall(response))
    has_commit = bool(_COMMIT_RE.search(response))
    s.task_structure = min(1.0, checkbox_hits / 5) * 0.7 + (0.3 if has_commit else 0.0)

    # Tier awareness
    s.tier_awareness = min(1.0, len(_TIER_RE.findall(response)) / 2)

    # Privacy pillar
    s.privacy_pillar = min(1.0, len(_PRIVACY_RE.findall(response)) / 3)

    # Safety pillar
    s.safety_pillar = min(1.0, len(_SAFETY_RE.findall(response)) / 2)

    # Accessibility
    s.accessibility = min(1.0, len(_A11Y_RE.findall(response)) / 2)

    # License split awareness
    s.license_split = min(1.0, len(_LICENSE_RE.findall(response)) / 2)

    # File paths: at least 3 plausible path references
    s.file_paths = min(1.0, len(_FILE_PATH_RE.findall(response)) / 3)

    # CF conventions
    s.cf_conventions = min(1.0, len(_CF_CONV_RE.findall(response)) / 2)

    # Length: 200–2500 words is healthy; outside = partial credit
    if 200 <= words <= 2500:
        s.length_ok = 1.0
    elif words < 200:
        s.length_ok = words / 200
    else:
        s.length_ok = max(0.0, 1.0 - (words - 2500) / 2500)

    return s


# ── Model client ───────────────────────────────────────────────────────────────

# Registry of named model targets (shorthand → {api_base, model_name})
MODEL_REGISTRY: dict[str, dict[str, str]] = {
    "deepseek-r1-1.5b": {
        "api_base": CF_TEXT_BASE,
        "model": "deepseek-r1-1.5b",
        "description": "DeepSeek R1 1.5B distill (cf-orch catalog key)",
    },
    "deepseek-r1-7b-4bit": {
        "api_base": CF_TEXT_BASE,
        "model": "deepseek-r1-7b-4bit",
        "description": "DeepSeek R1 7B distill, 4-bit (cf-orch catalog key)",
    },
    "deepseek-coder-6.7b-4bit": {
        "api_base": CF_TEXT_BASE,
        "model": "deepseek-coder-6.7b-4bit",
        "description": "DeepSeek Coder 6.7B instruct, 4-bit (cf-orch catalog key)",
    },
    "granite-4.1-8b": {
        "api_base": CF_TEXT_BASE,
        "model": "granite-4.1-8b",
        "description": "IBM Granite 4.1 8B, 4-bit (cf-orch catalog key)",
    },
    "qwen2.5-3b": {
        "api_base": CF_TEXT_BASE,
        "model": "qwen2.5-3b",
        "description": "Qwen 2.5 3B Q4 GGUF (cf-orch catalog key, navi only)",
    },
    "qwen2.5-7b": {
        "api_base": CF_TEXT_BASE,
        "model": "qwen2.5-7b",
        "description": "Qwen 2.5 7B Q4 GGUF (cf-orch catalog key, navi only)",
    },
}


# ── cf-orch allocation ─────────────────────────────────────────────────────────

def _cforch_allocate(
    model_id: str,
    cforch_url: str,
    startup_timeout_s: float = 300.0,
) -> tuple[str, str] | None:
    """Allocate a cf-text instance for model_id via the cf-orch coordinator.

    Returns (service_url, allocation_id) on success, None on failure.
    service_url is the direct node URL exposing /v1/chat/completions.
    """
    try:
        resp = httpx.post(
            f"{cforch_url}/api/services/cf-text/allocate",
            json={
                "model_candidates": [model_id],
                "caller": "avocet",
                "pipeline": "plans_benchmark",
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
            # Use \n so the SSE generator sees the line immediately
            print(f"  [cold start] loading {model_id!r} — polling every 3s…", flush=True)
            t0 = time.monotonic()
            deadline = t0 + startup_timeout_s
            probe_misses = 0

            while time.monotonic() < deadline:
                elapsed = time.monotonic() - t0
                try:
                    status = httpx.get(f"{cforch_url}/api/services/cf-text/status", timeout=5.0)
                    if status.is_success:
                        instances = status.json().get("instances", [])
                        match = next(
                            (i for i in instances
                             if i.get("node_id") == node_id and i.get("gpu_id") == gpu_id),
                            None,
                        )
                        if match:
                            probe_misses = 0
                            state = match.get("state", "")
                            if state == "running":
                                print(f"  [cold start] ready in {elapsed:.0f}s", flush=True)
                                return service_url, allocation_id
                            elif state == "stopped":
                                print(f"  [cold start] failed — service stopped after {elapsed:.0f}s", flush=True)
                                return None
                            else:
                                # still starting — emit keepalive so SSE stream stays alive
                                print(f"  [cold start] state={state!r}  elapsed={elapsed:.0f}s", flush=True)
                        else:
                            probe_misses += 1
                            print(f"  [cold start] waiting… elapsed={elapsed:.0f}s", flush=True)
                            if probe_misses >= 6:
                                try:
                                    h = httpx.get(f"{service_url}/health", timeout=3.0)
                                    if h.is_success:
                                        print(f"  [cold start] ready via health check in {elapsed:.0f}s", flush=True)
                                        return service_url, allocation_id
                                except Exception:
                                    pass
                    else:
                        print(f"  [cold start] status poll returned {status.status_code}, elapsed={elapsed:.0f}s", flush=True)
                except Exception as poll_exc:
                    print(f"  [cold start] poll error: {poll_exc}  elapsed={elapsed:.0f}s", flush=True)
                time.sleep(3.0)

            print(f"  [cold start] timed out after {time.monotonic()-t0:.0f}s", flush=True)
            return None

        return service_url, allocation_id
    except Exception as exc:
        print(f"[warn] cf-orch allocation failed for {model_id!r}: {exc}", file=sys.stderr)
        return None


def _call_model_direct(service_url: str, model: str, prompt: str, timeout: int = 600) -> tuple[str, float]:
    """Call an OpenAI-compatible /v1/chat/completions on a direct service URL."""
    t0 = time.monotonic()
    resp = httpx.post(
        f"{service_url.rstrip('/')}/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.2,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    latency = time.monotonic() - t0
    text = resp.json()["choices"][0]["message"]["content"]
    return text, latency


def _call_model(api_base: str, model: str, prompt: str, timeout: int = 180) -> tuple[str, float]:
    """Call an OpenAI-compatible /chat/completions endpoint. Returns (text, latency_s)."""
    t0 = time.monotonic()
    resp = httpx.post(
        f"{api_base}/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.2,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    latency = time.monotonic() - t0
    text = resp.json()["choices"][0]["message"]["content"]
    return text, latency


# ── Benchmark runner ───────────────────────────────────────────────────────────

@dataclass
class PromptResult:
    prompt_id: str
    prompt_name: str
    model_key: str
    response: str
    latency_s: float
    word_count: int
    scores: dict[str, float]
    total_score: float
    error: str | None = None


def run_benchmark(
    model_key: str,
    model_name: str,
    prompts: list[dict[str, Any]] | None = None,
    verbose: bool = False,
    # cf-orch path
    use_cforch: bool = False,
    cforch_url: str = CF_COORD_URL,
    # direct path (used when not cf-orch)
    api_base: str = CF_TEXT_BASE,
) -> list[PromptResult]:
    """Run all prompts through one model. Uses cf-orch allocation when use_cforch=True."""
    if prompts is None:
        prompts = HELD_OUT_PROMPTS

    # Allocate once per model when using cf-orch
    service_url: str | None = None
    if use_cforch:
        print(f"  Allocating {model_name!r} via cf-orch…", flush=True)
        alloc = _cforch_allocate(model_name, cforch_url)
        if alloc is None:
            # Return all prompts as errors
            return [
                PromptResult(
                    prompt_id=p["id"], prompt_name=p["name"], model_key=model_key,
                    response="", latency_s=0.0, word_count=0, scores={}, total_score=0.0,
                    error=f"cf-orch allocation failed for {model_name!r}",
                )
                for p in prompts
            ]
        service_url, _alloc_id = alloc

    results: list[PromptResult] = []
    for p in prompts:
        if verbose:
            print(f"  [{p['id']}] {p['name']} … ", end="", flush=True)
        try:
            if service_url:
                response, latency = _call_model_direct(service_url, model_name, p["prompt"])
            else:
                response, latency = _call_model(api_base, model_name, p["prompt"])
            rubric = score_response(response, p)
            result = PromptResult(
                prompt_id=p["id"],
                prompt_name=p["name"],
                model_key=model_key,
                response=response,
                latency_s=round(latency, 2),
                word_count=len(response.split()),
                scores=rubric.as_dict(),
                total_score=round(rubric.total(), 3),
            )
            if verbose:
                print(f"score={result.total_score:.3f}  ({result.word_count}w, {latency:.1f}s)")
        except Exception as exc:
            result = PromptResult(
                prompt_id=p["id"],
                prompt_name=p["name"],
                model_key=model_key,
                response="",
                latency_s=0.0,
                word_count=0,
                scores={},
                total_score=0.0,
                error=str(exc),
            )
            if verbose:
                print(f"ERROR: {exc}")
        results.append(result)
    return results


# ── Reporting ──────────────────────────────────────────────────────────────────

def _print_single_report(results: list[PromptResult], model_key: str) -> None:
    ok = [r for r in results if not r.error]
    err = [r for r in results if r.error]
    if not ok:
        print(f"\n[{model_key}] All {len(err)} prompts failed.\n")
        return

    avg_total = sum(r.total_score for r in ok) / len(ok)
    avg_latency = sum(r.latency_s for r in ok) / len(ok)

    # Aggregate per-rubric averages
    rubric_keys = list(ok[0].scores.keys())
    rubric_avgs = {k: sum(r.scores.get(k, 0) for r in ok) / len(ok) for k in rubric_keys}

    print(f"\n{'='*60}")
    print(f"  Model : {model_key}")
    print(f"  Prompts: {len(ok)}/{len(results)} passed  ({len(err)} errors)")
    print(f"  Overall score : {avg_total:.3f}  (avg latency {avg_latency:.1f}s)")
    print(f"\n  Rubric breakdown:")
    for k, v in sorted(rubric_avgs.items(), key=lambda x: -x[1]):
        bar = "█" * int(v * 20)
        print(f"    {k:<22} {v:.3f}  {bar}")
    print(f"\n  Per-prompt scores:")
    for r in sorted(ok, key=lambda x: -x.total_score):
        flag = "⚠" if r.total_score < 0.3 else " "
        print(f"    {flag} {r.prompt_id} {r.prompt_name:<35} {r.total_score:.3f}  ({r.word_count}w)")
    if err:
        print(f"\n  Errors:")
        for r in err:
            print(f"    {r.prompt_id} {r.prompt_name}: {r.error}")
    print(f"{'='*60}\n")


def _print_comparison_table(all_results: dict[str, list[PromptResult]]) -> None:
    model_keys = list(all_results.keys())
    prompt_ids = [p["id"] for p in HELD_OUT_PROMPTS]

    # Scores by (model, prompt_id)
    score_map: dict[tuple[str, str], float] = {}
    for mk, results in all_results.items():
        for r in results:
            score_map[(mk, r.prompt_id)] = r.total_score if not r.error else 0.0

    col_w = 10
    header = f"{'Prompt':<35}" + "".join(f"{mk[:col_w-1]:<{col_w}}" for mk in model_keys)
    print(f"\n{'='*len(header)}")
    print("  COMPARISON TABLE")
    print(f"{'='*len(header)}")
    print(f"  {header}")
    print(f"  {'-'*len(header)}")

    for pid in prompt_ids:
        pname = next(p["name"] for p in HELD_OUT_PROMPTS if p["id"] == pid)
        row = f"  {pname:<35}"
        best = max(score_map.get((mk, pid), 0.0) for mk in model_keys)
        for mk in model_keys:
            v = score_map.get((mk, pid), 0.0)
            marker = "*" if v == best and len(model_keys) > 1 else " "
            row += f"{v:.3f}{marker}   "
        print(row)

    print(f"  {'-'*len(header)}")
    avgs_row = f"  {'AVERAGE':<35}"
    best_avg = -1.0
    avgs: dict[str, float] = {}
    for mk in model_keys:
        vals = [score_map.get((mk, pid), 0.0) for pid in prompt_ids]
        avgs[mk] = sum(vals) / len(vals)
        best_avg = max(best_avg, avgs[mk])
    for mk in model_keys:
        marker = "*" if avgs[mk] == best_avg and len(model_keys) > 1 else " "
        avgs_row += f"{avgs[mk]:.3f}{marker}   "
    print(avgs_row)
    print(f"{'='*len(header)}\n")
    if len(model_keys) > 1:
        winner = max(avgs, key=lambda k: avgs[k])
        print(f"  Winner: {winner}  (avg {avgs[winner]:.3f})\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-models", action="store_true",
                        help="Print registered model shortcuts and exit")
    parser.add_argument("--model", metavar="KEY",
                        help="Benchmark a single model (registry key or raw model name)")
    parser.add_argument("--compare", nargs="+", metavar="KEY",
                        help="Compare two or more models side-by-side")
    parser.add_argument("--cforch", action="store_true",
                        help="Route inference through cf-orch coordinator (allocate per model)")
    parser.add_argument("--cforch-url", default=CF_COORD_URL, metavar="URL",
                        help=f"cf-orch coordinator URL (default: {CF_COORD_URL})")
    parser.add_argument("--api-base", default=None,
                        help="Direct API base URL when not using cf-orch")
    parser.add_argument("--model-name", default=None,
                        help="Override model name sent to API (single-model runs only)")
    parser.add_argument("--prompts", nargs="+", metavar="ID",
                        help="Run only specific prompt IDs (e.g. ho_001 ho_003)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Write detailed JSON results to this path")
    parser.add_argument("--workers", type=int, default=1, metavar="N",
                        help="Run N models concurrently (default 1). Set to number of available nodes.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print per-prompt progress")
    args = parser.parse_args()

    if args.list_models:
        print("\nRegistered model shortcuts:")
        for key, info in MODEL_REGISTRY.items():
            print(f"  {key:<20} {info['description']}")
        print(f"\nDefault endpoints:")
        print(f"  direct    {CF_TEXT_BASE}")
        print(f"  cf-orch   {CF_COORD_URL}")
        return

    prompts = HELD_OUT_PROMPTS
    if args.prompts:
        ids = set(args.prompts)
        prompts = [p for p in HELD_OUT_PROMPTS if p["id"] in ids]
        if not prompts:
            print(f"No prompts matched IDs: {args.prompts}", file=sys.stderr)
            sys.exit(1)

    model_keys: list[str] = []
    if args.compare:
        model_keys = args.compare
    elif args.model:
        model_keys = [args.model]
    else:
        parser.print_help()
        sys.exit(0)

    all_results: dict[str, list[PromptResult]] = {}
    print_lock = threading.Lock()

    def _run_one(mk: str) -> tuple[str, list[PromptResult]]:
        if mk in MODEL_REGISTRY:
            reg = MODEL_REGISTRY[mk]
            model_name = args.model_name or reg["model"]
            direct_base = args.api_base or reg["api_base"]
        else:
            model_name = args.model_name or mk
            direct_base = args.api_base or CF_TEXT_BASE

        if args.cforch:
            with print_lock:
                print(f"\nRunning [{mk}] via cf-orch ({args.cforch_url})  model={model_name}")
            results = run_benchmark(
                mk, model_name, prompts=prompts, verbose=args.verbose,
                use_cforch=True, cforch_url=args.cforch_url,
            )
        else:
            with print_lock:
                print(f"\nRunning [{mk}] → {direct_base}  model={model_name}")
            results = run_benchmark(
                mk, model_name, prompts=prompts, verbose=args.verbose,
                api_base=direct_base,
            )

        with print_lock:
            _print_single_report(results, mk)
        return mk, results

    workers = max(1, args.workers)
    if workers == 1 or len(model_keys) == 1:
        for mk in model_keys:
            mk_out, results = _run_one(mk)
            all_results[mk_out] = results
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_one, mk): mk for mk in model_keys}
            for fut in as_completed(futures):
                mk_out, results = fut.result()
                all_results[mk_out] = results

    if len(model_keys) > 1:
        _print_comparison_table(all_results)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            mk: [asdict(r) for r in results]
            for mk, results in all_results.items()
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Wrote detailed results to {args.output}")


if __name__ == "__main__":
    main()
