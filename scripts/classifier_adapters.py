"""Classifier adapters for email classification benchmark.

Each adapter wraps a HuggingFace model and normalizes output to LABELS.
Models load lazily on first classify() call; call unload() to free VRAM.
"""
from __future__ import annotations

import abc
from collections import defaultdict
import httpx
import logging
from pathlib import Path
from typing import Any

__all__ = [
    "LABELS",
    "LABEL_DESCRIPTIONS",
    "DEFAULT_EXEMPLARS",
    "compute_metrics",
    "ClassifierAdapter",
    "ZeroShotAdapter",
    "GLiClassAdapter",
    "RerankerAdapter",
    "FineTunedAdapter",
    "EmbeddingKNNAdapter",
]

_logger = logging.getLogger(__name__)

LABELS: list[str] = [
    "interview_scheduled",
    "offer_received",
    "rejected",
    "positive_response",
    "survey_received",
    "neutral",
    "event_rescheduled",
    "digest",
    "new_lead",
    "hired",
]

# Natural-language descriptions used by the RerankerAdapter.
LABEL_DESCRIPTIONS: dict[str, str] = {
    "interview_scheduled": "scheduling an interview, phone screen, or video call",
    "offer_received": "a formal job offer or employment offer letter",
    "rejected": "application rejected or not moving forward with candidacy",
    "positive_response": "positive recruiter interest or request to connect",
    "survey_received": "invitation to complete a culture-fit survey or assessment",
    "neutral": "automated ATS confirmation such as application received",
    "event_rescheduled": "an interview or scheduled event moved to a new time",
    "digest": "job digest or multi-listing email with multiple job postings",
    "new_lead": "unsolicited recruiter outreach or cold contact about a new opportunity",
    "hired": "job offer accepted, onboarding logistics, welcome email, or start date confirmation",
}

# Lazy import shims — allow tests to patch without requiring the libs installed.
try:
    from transformers import pipeline  # type: ignore[assignment]
except ImportError:
    pipeline = None  # type: ignore[assignment]

try:
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline  # type: ignore
    from transformers import AutoTokenizer
except ImportError:
    GLiClassModel = None  # type: ignore
    ZeroShotClassificationPipeline = None  # type: ignore
    AutoTokenizer = None  # type: ignore

try:
    from FlagEmbedding import FlagReranker  # type: ignore
except ImportError:
    FlagReranker = None  # type: ignore


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def compute_metrics(
    predictions: list[str],
    gold: list[str],
    labels: list[str],
) -> dict[str, Any]:
    """Return per-label precision/recall/F1 + macro_f1 + accuracy."""
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    for pred, true in zip(predictions, gold):
        if pred == true:
            tp[pred] += 1
        else:
            fp[pred] += 1
            fn[true] += 1

    result: dict[str, Any] = {}
    for label in labels:
        denom_p = tp[label] + fp[label]
        denom_r = tp[label] + fn[label]
        p = tp[label] / denom_p if denom_p else 0.0
        r = tp[label] / denom_r if denom_r else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        result[label] = {
            "precision": p,
            "recall": r,
            "f1": f1,
            "support": denom_r,
        }

    labels_with_support = [label for label in labels if result[label]["support"] > 0]
    if labels_with_support:
        result["__macro_f1__"] = (
            sum(result[label]["f1"] for label in labels_with_support) / len(labels_with_support)
        )
    else:
        result["__macro_f1__"] = 0.0
    result["__accuracy__"] = sum(tp.values()) / len(predictions) if predictions else 0.0
    return result



def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


DEFAULT_EXEMPLARS: dict[str, list[str]] = {
    "interview_scheduled": [
        "Subject: Interview Invitation\n\nWe would like to invite you for a phone screen next week.",
        "Subject: Schedule a call\n\nCould you be available for a video interview on Tuesday?",
        "Subject: Next Steps\n\nWe'd like to move forward with a technical interview. Please select a time.",
        "Subject: Interview Details\n\nHere are the dial-in instructions for your interview tomorrow.",
    ],
    "offer_received": [
        "Subject: Offer Letter Enclosed\n\nWe are pleased to extend you an offer of employment.",
        "Subject: Job Offer\n\nDear candidate, we are excited to offer you the position of Software Engineer.",
        "Subject: Employment Offer\n\nPlease find attached your formal offer letter and compensation details.",
        "Subject: Offer of Employment\n\nCongratulations! We would like to offer you a full-time position.",
    ],
    "rejected": [
        "Subject: Your Application\n\nAfter careful consideration, we have decided to move forward with other candidates.",
        "Subject: Application Status\n\nWe regret to inform you that your application has not been selected.",
        "Subject: Thank you for applying\n\nWe appreciate your interest but have chosen not to proceed.",
        "Subject: Update on your candidacy\n\nWe will not be moving forward with your application at this time.",
    ],
    "positive_response": [
        "Subject: Your profile\n\nI came across your LinkedIn and think you would be a great fit for our team.",
        "Subject: Exciting opportunity\n\nWe were impressed by your background and would love to connect.",
        "Subject: Following up\n\nThank you for your interest — we'd like to learn more about your experience.",
        "Subject: Great fit\n\nYour skills align well with what we are looking for. Let's set up a call.",
    ],
    "survey_received": [
        "Subject: Candidate Experience Survey\n\nPlease complete this brief survey about your application experience.",
        "Subject: Culture Fit Assessment\n\nAs part of our process, we ask all candidates to complete a short assessment.",
        "Subject: Skills Assessment\n\nWe'd like you to complete our online coding assessment before proceeding.",
        "Subject: Personality Assessment\n\nPlease complete the following assessment as the next step in our process.",
        "Subject: Pre-interview questionnaire\n\nBefore we schedule your interview, please complete this brief skills survey.",
    ],
    "neutral": [
        "Subject: Application Received\n\nWe have received your application and will be in touch.",
        "Subject: Thank you for applying\n\nYour application is under review. We will contact you if needed.",
        "Subject: Confirmation\n\nThis email confirms receipt of your application to our company.",
        "Subject: Application Confirmation\n\nThank you for your interest. We will review your materials and follow up.",
    ],
    "event_rescheduled": [
        "Subject: Interview Rescheduled\n\nDue to a conflict, we need to move your interview to a new time.",
        "Subject: Change of interview time\n\nWe apologize — your interview has been rescheduled to Thursday.",
        "Subject: Updated interview details\n\nYour interview has been moved from Monday to Wednesday at 2pm.",
        "Subject: Reschedule request\n\nWould you be available to reschedule to a different time slot?",
        "Subject: New interview time\n\nYour phone screen has been moved from tomorrow to next week.",
    ],
    "digest": [
        "Subject: 15 new jobs matching your search\n\nHere are the latest job postings that match your profile.",
        "Subject: Weekly Job Digest\n\nThis week's top opportunities for Software Engineers in your area.",
        "Subject: Jobs you might like\n\nBased on your profile, here are some positions we recommend.",
        "Subject: New jobs for you\n\nSee the latest openings from companies on your watchlist.",
    ],
    "new_lead": [
        "Subject: Exciting opportunity at our company\n\nHi, I noticed your background and think you'd be a great fit.",
        "Subject: Are you open to new opportunities?\n\nI'm a recruiter reaching out about a role matching your experience.",
        "Subject: Quick question\n\nWould you be interested in hearing about a senior engineering role?",
        "Subject: Recruiting outreach\n\nI came across your profile and wanted to share an exciting opening.",
    ],
    "hired": [
        "Subject: Welcome to the team!\n\nWe are thrilled to have you join us. Here are your onboarding details.",
        "Subject: Onboarding information\n\nCongratulations on accepting our offer. Your start date is confirmed.",
        "Subject: First day information\n\nWe look forward to your first day. Please arrive at 9am and ask for HR.",
        "Subject: Background check initiated\n\nAs part of your onboarding, we have initiated a background check.",
        "Subject: Equipment setup\n\nYour laptop and equipment will be ready for pickup on your first day.",
    ],
}


class ClassifierAdapter(abc.ABC):
    """Abstract base for all email classifier adapters."""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def model_id(self) -> str: ...

    @abc.abstractmethod
    def load(self) -> None:
        """Download/load the model into memory."""

    @abc.abstractmethod
    def unload(self) -> None:
        """Release model from memory."""

    @abc.abstractmethod
    def classify(self, subject: str, body: str) -> str:
        """Return one of LABELS for the given email."""


class ZeroShotAdapter(ClassifierAdapter):
    """Wraps any transformers zero-shot-classification pipeline.

    load() calls pipeline("zero-shot-classification", model=..., device=...) to get
    an inference callable, stored as self._pipeline.  classify() then calls
    self._pipeline(text, LABELS, multi_label=False).  In tests, patch
    'scripts.classifier_adapters.pipeline' with a MagicMock whose .return_value is
    itself a MagicMock(return_value={...}) to simulate both the factory call and the
    inference call.

    two_pass: if True, classify() runs a second pass restricted to the top-2 labels
    from the first pass, forcing a binary choice.  This typically improves confidence
    without the accuracy cost of a full 6-label second run.
    """

    def __init__(self, name: str, model_id: str, two_pass: bool = False) -> None:
        self._name = name
        self._model_id = model_id
        self._pipeline: Any = None
        self._two_pass = two_pass

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return self._model_id

    def load(self) -> None:
        import scripts.classifier_adapters as _mod  # noqa: PLC0415
        _pipe_fn = _mod.pipeline
        if _pipe_fn is None:
            raise ImportError("transformers not installed — run: pip install transformers")
        device = 0 if _cuda_available() else -1
        # Instantiate the pipeline once; classify() calls the resulting object on each text.
        self._pipeline = _pipe_fn("zero-shot-classification", model=self._model_id, device=device)

    def unload(self) -> None:
        self._pipeline = None

    def classify(self, subject: str, body: str) -> str:
        if self._pipeline is None:
            self.load()
        text = f"Subject: {subject}\n\n{body[:600]}"
        result = self._pipeline(text, LABELS, multi_label=False)
        if self._two_pass and len(result["labels"]) >= 2:
            top2 = result["labels"][:2]
            result = self._pipeline(text, top2, multi_label=False)
        return result["labels"][0]


class GLiClassAdapter(ClassifierAdapter):
    """Wraps knowledgator GLiClass models via the gliclass library."""

    def __init__(self, name: str, model_id: str) -> None:
        self._name = name
        self._model_id = model_id
        self._pipeline: Any = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return self._model_id

    def load(self) -> None:
        if GLiClassModel is None:
            raise ImportError("gliclass not installed — run: pip install gliclass")
        device = "cuda:0" if _cuda_available() else "cpu"
        model = GLiClassModel.from_pretrained(self._model_id)
        tokenizer = AutoTokenizer.from_pretrained(self._model_id)
        self._pipeline = ZeroShotClassificationPipeline(
            model,
            tokenizer,
            classification_type="single-label",
            device=device,
        )

    def unload(self) -> None:
        self._pipeline = None

    def classify(self, subject: str, body: str) -> str:
        if self._pipeline is None:
            self.load()
        text = f"Subject: {subject}\n\n{body[:600]}"
        results = self._pipeline(text, LABELS, threshold=0.0)[0]
        return max(results, key=lambda r: r["score"])["label"]


class RerankerAdapter(ClassifierAdapter):
    """Uses a BGE reranker to score (email, label_description) pairs."""

    def __init__(self, name: str, model_id: str) -> None:
        self._name = name
        self._model_id = model_id
        self._reranker: Any = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return self._model_id

    def load(self) -> None:
        if FlagReranker is None:
            raise ImportError("FlagEmbedding not installed — run: pip install FlagEmbedding")
        self._reranker = FlagReranker(self._model_id, use_fp16=_cuda_available())

    def unload(self) -> None:
        self._reranker = None

    def classify(self, subject: str, body: str) -> str:
        if self._reranker is None:
            self.load()
        text = f"Subject: {subject}\n\n{body[:600]}"
        pairs = [[text, LABEL_DESCRIPTIONS.get(label, label.replace("_", " "))] for label in LABELS]
        scores: list[float] = self._reranker.compute_score(pairs, normalize=True)
        return LABELS[scores.index(max(scores))]


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
            raise ImportError("transformers not installed — run: pip install transformers")
        device = 0 if _cuda_available() else -1
        self._pipeline = _pipe_fn("text-classification", model=self._model_dir, device=device)

    def unload(self) -> None:
        self._pipeline = None

    def classify(self, subject: str, body: str) -> str:
        if self._pipeline is None:
            self.load()
        text = f"{subject} [SEP] {body[:400]}"
        result = self._pipeline(text)
        return result[0]["label"]


class EmbeddingKNNAdapter(ClassifierAdapter):
    """k-NN email classifier using Ollama /v1/embeddings via cf-orch allocation.

    load():
      1. Allocates an Ollama instance from cf-orch (POST /api/services/ollama/allocate).
         Falls back to ollama_url directly if orch allocation fails or is not configured.
      2. Pre-embeds all exemplar texts and stores per-label vector lists.

    classify(subject, body):
      Embeds the input email, computes cosine similarity against all stored exemplar
      vectors, and majority-votes the top-k labels (default k=3). Tie-break: label
      with the highest total similarity score among tied vote counts wins.

    unload():
      Releases the cf-orch allocation (DELETE .../allocations/{id}) and clears state.
    """

    def __init__(
        self,
        name: str,
        model_id: str,
        *,
        k: int = 3,
        orch_url: str = "",
        ollama_url: str = "",
        exemplar_texts: dict[str, list[str]] | None = None,
    ) -> None:
        self._name = name
        self._model_id = model_id
        self._k = k
        self._orch_url = orch_url
        self._ollama_url = ollama_url
        self._exemplar_texts: dict[str, list[str]] = (
            exemplar_texts if exemplar_texts is not None else DEFAULT_EXEMPLARS
        )
        self._exemplar_embeddings: dict[str, list[list[float]]] = {}
        self._node_url: str = ""
        self._allocation_id: str = ""
        self._orch_url_used: str = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return self._model_id

    def _resolve_urls(self) -> tuple[str, str]:
        if self._orch_url or self._ollama_url:
            return self._orch_url, self._ollama_url
        import yaml  # noqa: PLC0415
        cfg_path = Path(__file__).parent.parent / "config" / "label_tool.yaml"
        cfg: dict = {}
        if cfg_path.exists():
            try:
                cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                pass
        cforch = cfg.get("cforch", {}) or {}
        return cforch.get("coordinator_url", ""), cforch.get("ollama_url", "")

    def _embed(self, node_url: str, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            f"{node_url}/v1/embeddings",
            json={"model": self._model_id, "input": texts},
            timeout=30.0,
        )
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]

    def load(self) -> None:
        if self._allocation_id or self._exemplar_embeddings:
            raise RuntimeError(
                "EmbeddingKNNAdapter.load() called while already loaded — call unload() first"
            )
        orch_url, ollama_url = self._resolve_urls()
        node_url = ""
        orch_url_used = ""
        if orch_url:
            try:
                resp = httpx.post(
                    f"{orch_url}/api/services/ollama/allocate",
                    json={"model": self._model_id},
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    node_url = data["url"]
                    self._allocation_id = data["allocation_id"]
                    orch_url_used = orch_url
            except Exception as exc:
                _logger.warning(
                    "cf-orch allocation failed, falling back to direct ollama_url: %s", exc
                )
        if not node_url:
            node_url = ollama_url
            self._allocation_id = ""
            orch_url_used = ""
        self._node_url = node_url
        self._orch_url_used = orch_url_used
        try:
            embeddings: dict[str, list[list[float]]] = {}
            for label, texts in self._exemplar_texts.items():
                embeddings[label] = self._embed(node_url, texts)
            self._exemplar_embeddings = embeddings
        except Exception:
            self.unload()
            raise

    def unload(self) -> None:
        if self._allocation_id and self._orch_url_used:
            try:
                httpx.request(
                    "DELETE",
                    f"{self._orch_url_used}/api/services/ollama/allocations/{self._allocation_id}",
                    timeout=10.0,
                )
            except Exception:
                pass
        self._exemplar_embeddings = {}
        self._node_url = ""
        self._allocation_id = ""
        self._orch_url_used = ""

    def classify(self, subject: str, body: str) -> str:
        if not self._exemplar_embeddings:
            self.load()
        text = f"Subject: {subject}\n\n{body[:600]}"
        [query_vec] = self._embed(self._node_url, [text])
        scored: list[tuple[float, str]] = [
            (_cosine(query_vec, vec), label)
            for label, vecs in self._exemplar_embeddings.items()
            for vec in vecs
        ]
        top_k = sorted(scored, reverse=True)[: self._k]
        votes: dict[str, list[float]] = {}
        for score, label in top_k:
            votes.setdefault(label, []).append(score)
        return max(
            votes,
            key=lambda lbl: (len(votes[lbl]), sum(votes[lbl])),
        )
