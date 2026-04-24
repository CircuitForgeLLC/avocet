"""Tests for app/models.py — /api/models/* endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_models_globals(tmp_path):
    """Redirect module-level dirs to tmp_path and reset download progress."""
    from app import models as models_module

    prev_models = models_module._MODELS_DIR
    prev_queue = models_module._QUEUE_DIR
    prev_progress = dict(models_module._download_progress)

    models_dir = tmp_path / "models"
    queue_dir = tmp_path / "data"
    models_dir.mkdir()
    queue_dir.mkdir()

    models_module.set_models_dir(models_dir)
    models_module.set_queue_dir(queue_dir)
    models_module._download_progress = {}

    yield

    models_module.set_models_dir(prev_models)
    models_module.set_queue_dir(prev_queue)
    models_module._download_progress = prev_progress


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def _make_hf_response(repo_id: str = "org/model", pipeline_tag: str = "text-classification") -> dict:
    """Minimal HF API response payload."""
    return {
        "modelId": repo_id,
        "pipeline_tag": pipeline_tag,
        "tags": ["pytorch", pipeline_tag],
        "downloads": 42000,
        "siblings": [
            {"rfilename": "pytorch_model.bin", "size": 500_000_000},
        ],
        "cardData": {"description": "A test model description."},
    }


def _queue_one(client, repo_id: str = "org/model") -> dict:
    """Helper: POST to /queue and return the created entry."""
    r = client.post("/api/models/queue", json={
        "repo_id": repo_id,
        "pipeline_tag": "text-classification",
        "adapter_recommendation": "ZeroShotAdapter",
    })
    assert r.status_code == 201, r.text
    return r.json()


# ── GET /lookup ────────────────────────────────────────────────────────────────

def test_lookup_invalid_repo_id_returns_422_no_slash(client):
    """repo_id without a '/' should be rejected with 422."""
    r = client.get("/api/models/lookup", params={"repo_id": "noslash"})
    assert r.status_code == 422


def test_lookup_invalid_repo_id_returns_422_whitespace(client):
    """repo_id containing whitespace should be rejected with 422."""
    r = client.get("/api/models/lookup", params={"repo_id": "org/model name"})
    assert r.status_code == 422


def test_lookup_hf_404_returns_404(client):
    """HF API returning 404 should surface as HTTP 404."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "org/nonexistent"})

    assert r.status_code == 404


def test_lookup_hf_network_error_returns_502(client):
    """Network error reaching HF API should return 502."""
    import httpx as _httpx

    with patch("app.models.httpx.get", side_effect=_httpx.RequestError("timeout")):
        r = client.get("/api/models/lookup", params={"repo_id": "org/model"})

    assert r.status_code == 502


def test_lookup_returns_correct_shape(client):
    """Successful lookup returns all required fields."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_hf_response("org/mymodel", "text-classification")

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "org/mymodel"})

    assert r.status_code == 200
    data = r.json()
    assert data["repo_id"] == "org/mymodel"
    assert data["pipeline_tag"] == "text-classification"
    assert data["adapter_recommendation"] == "ZeroShotAdapter"
    assert data["model_size_bytes"] == 500_000_000
    assert data["downloads"] == 42000
    assert data["already_installed"] is False
    assert data["already_queued"] is False


def test_lookup_unknown_pipeline_tag_returns_null_adapter_and_incompatible(client):
    """An unrecognised pipeline_tag yields adapter_recommendation=null and compatible=False."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_hf_response("org/m", "reinforcement-learning")

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "org/m"})

    assert r.status_code == 200
    data = r.json()
    assert data["adapter_recommendation"] is None
    assert data["compatible"] is False
    assert data["role"] is None
    assert data["service"] is None
    assert "CircuitForge model ecosystem" in data["warning"]


def test_lookup_stt_tag_returns_compatible_with_cf_stt_service(client):
    """automatic-speech-recognition tag yields compatible=True, service=cf-stt."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_hf_response("openai/whisper-base", "automatic-speech-recognition")

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "openai/whisper-base"})

    assert r.status_code == 200
    data = r.json()
    assert data["compatible"] is True
    assert data["adapter_recommendation"] is None
    assert data["role"] == "stt"
    assert data["service"] == "cf-stt"
    assert data["warning"] is None


def test_lookup_vision_tag_returns_compatible_with_cf_vision_service(client):
    """image-classification tag yields compatible=True, service=cf-vision."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_hf_response("google/siglip-base", "image-classification")

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "google/siglip-base"})

    assert r.status_code == 200
    data = r.json()
    assert data["compatible"] is True
    assert data["role"] == "vision"
    assert data["service"] == "cf-vision"


def test_lookup_audio_classification_tag_returns_cf_voice_service(client):
    """audio-classification tag yields compatible=True, service=cf-voice."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_hf_response("org/audio-model", "audio-classification")

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "org/audio-model"})

    assert r.status_code == 200
    data = r.json()
    assert data["compatible"] is True
    assert data["role"] == "classifier"
    assert data["service"] == "cf-voice"


def test_lookup_embedding_tag_returns_compatible_with_cf_core_service(client):
    """feature-extraction tag yields compatible=True, service=cf-core."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_hf_response("BAAI/bge-small-en", "feature-extraction")

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "BAAI/bge-small-en"})

    assert r.status_code == 200
    data = r.json()
    assert data["compatible"] is True
    assert data["role"] == "embedding"
    assert data["service"] == "cf-core"


def test_lookup_already_queued_flag(client):
    """already_queued is True when repo_id is in the pending queue."""
    _queue_one(client, "org/queued-model")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_hf_response("org/queued-model")

    with patch("app.models.httpx.get", return_value=mock_resp):
        r = client.get("/api/models/lookup", params={"repo_id": "org/queued-model"})

    assert r.status_code == 200
    assert r.json()["already_queued"] is True


# ── GET /queue ─────────────────────────────────────────────────────────────────

def test_queue_empty_initially(client):
    r = client.get("/api/models/queue")
    assert r.status_code == 200
    assert r.json() == []


def test_queue_add_and_list(client):
    """POST then GET /queue should return the entry."""
    entry = _queue_one(client, "org/my-model")

    r = client.get("/api/models/queue")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["repo_id"] == "org/my-model"
    assert items[0]["status"] == "pending"
    assert items[0]["id"] == entry["id"]


def test_queue_add_returns_entry_fields(client):
    """POST /queue returns an entry with all expected fields."""
    entry = _queue_one(client)
    assert "id" in entry
    assert "queued_at" in entry
    assert entry["status"] == "pending"
    assert entry["pipeline_tag"] == "text-classification"
    assert entry["adapter_recommendation"] == "ZeroShotAdapter"


def test_queue_preserves_role_and_service(client):
    """POST /queue with role/service fields round-trips them through GET /queue."""
    r = client.post("/api/models/queue", json={
        "repo_id": "openai/whisper-base",
        "pipeline_tag": "automatic-speech-recognition",
        "adapter_recommendation": None,
        "role": "stt",
        "service": "cf-stt",
    })
    assert r.status_code == 201
    entry = r.json()
    assert entry["role"] == "stt"
    assert entry["service"] == "cf-stt"

    r2 = client.get("/api/models/queue")
    items = r2.json()
    assert items[0]["role"] == "stt"
    assert items[0]["service"] == "cf-stt"


# ── POST /queue — 409 duplicate ────────────────────────────────────────────────

def test_queue_duplicate_returns_409(client):
    """Posting the same repo_id twice should return 409."""
    _queue_one(client, "org/dup-model")

    r = client.post("/api/models/queue", json={
        "repo_id": "org/dup-model",
        "pipeline_tag": "text-classification",
        "adapter_recommendation": "ZeroShotAdapter",
    })
    assert r.status_code == 409


def test_queue_multiple_different_models(client):
    """Multiple distinct repo_ids should all be accepted."""
    _queue_one(client, "org/model-a")
    _queue_one(client, "org/model-b")
    _queue_one(client, "org/model-c")

    r = client.get("/api/models/queue")
    assert r.status_code == 200
    assert len(r.json()) == 3


# ── DELETE /queue/{id} — dismiss ──────────────────────────────────────────────

def test_queue_dismiss(client):
    """DELETE /queue/{id} sets status=dismissed; entry not returned by GET /queue."""
    entry = _queue_one(client)
    entry_id = entry["id"]

    r = client.delete(f"/api/models/queue/{entry_id}")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    r2 = client.get("/api/models/queue")
    assert r2.status_code == 200
    assert r2.json() == []


def test_queue_dismiss_nonexistent_returns_404(client):
    """DELETE /queue/{id} with unknown id returns 404."""
    r = client.delete("/api/models/queue/does-not-exist")
    assert r.status_code == 404


def test_queue_dismiss_allows_re_queue(client):
    """After dismissal the same repo_id can be queued again."""
    entry = _queue_one(client, "org/requeue-model")
    client.delete(f"/api/models/queue/{entry['id']}")

    r = client.post("/api/models/queue", json={
        "repo_id": "org/requeue-model",
        "pipeline_tag": None,
        "adapter_recommendation": None,
    })
    assert r.status_code == 201


# ── POST /queue/{id}/approve ───────────────────────────────────────────────────

def test_approve_nonexistent_returns_404(client):
    """Approving an unknown id returns 404."""
    r = client.post("/api/models/queue/ghost-id/approve")
    assert r.status_code == 404


def test_approve_non_pending_returns_409(client):
    """Approving an entry that is not in 'pending' state returns 409."""
    from app import models as models_module

    entry = _queue_one(client)
    # Manually flip status to 'failed'
    models_module._update_queue_entry(entry["id"], {"status": "failed"})

    r = client.post(f"/api/models/queue/{entry['id']}/approve")
    assert r.status_code == 409


def test_approve_starts_download_and_returns_ok(client):
    """Approving a pending entry returns {ok: true} and starts a background thread."""
    import time
    import threading

    entry = _queue_one(client)

    # Patch snapshot_download so the thread doesn't actually hit the network.
    # Use an Event so we can wait for the thread to finish before asserting.
    thread_done = threading.Event()
    original_run = None

    def _fake_snapshot_download(**kwargs):
        pass

    with patch("app.models.snapshot_download", side_effect=_fake_snapshot_download):
        r = client.post(f"/api/models/queue/{entry['id']}/approve")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # Give the background thread a moment to complete while snapshot_download is patched
        time.sleep(0.3)

        # Queue entry status should have moved to 'downloading' (or 'ready' if fast)
        from app import models as models_module
        updated = models_module._get_queue_entry(entry["id"])
        assert updated is not None, "Queue entry not found — thread may have run after fixture teardown"
        assert updated["status"] in ("downloading", "ready", "failed")


# ── GET /download/stream ───────────────────────────────────────────────────────

def test_download_stream_idle_when_no_download(client):
    """GET /download/stream returns a single idle event when nothing is downloading."""
    r = client.get("/api/models/download/stream")
    assert r.status_code == 200
    # SSE body should contain the idle event
    assert "idle" in r.text


# ── GET /installed ─────────────────────────────────────────────────────────────

def test_installed_empty(client):
    """GET /installed returns [] when models dir is empty."""
    r = client.get("/api/models/installed")
    assert r.status_code == 200
    assert r.json() == []


def test_installed_detects_downloaded_model(client, tmp_path):
    """A subdir with config.json is surfaced as type='downloaded'."""
    from app import models as models_module

    model_dir = models_module._MODELS_DIR / "org--mymodel"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({"model_type": "bert"}), encoding="utf-8")
    (model_dir / "model_info.json").write_text(
        json.dumps({
            "repo_id": "org/mymodel",
            "adapter_recommendation": "ZeroShotAdapter",
            "role": "classifier",
            "service": "avocet",
        }),
        encoding="utf-8",
    )

    r = client.get("/api/models/installed")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["type"] == "downloaded"
    assert items[0]["name"] == "org--mymodel"
    assert items[0]["adapter"] == "ZeroShotAdapter"
    assert items[0]["model_id"] == "org/mymodel"
    assert items[0]["role"] == "classifier"
    assert items[0]["service"] == "avocet"


def test_installed_stt_model_surfaces_role_and_service(client):
    """A downloaded STT model's role/service are returned by GET /installed."""
    from app import models as models_module

    model_dir = models_module._MODELS_DIR / "openai--whisper-base"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({"model_type": "whisper"}), encoding="utf-8")
    (model_dir / "model_info.json").write_text(
        json.dumps({
            "repo_id": "openai/whisper-base",
            "adapter_recommendation": None,
            "role": "stt",
            "service": "cf-stt",
        }),
        encoding="utf-8",
    )

    r = client.get("/api/models/installed")
    assert r.status_code == 200
    items = r.json()
    assert items[0]["role"] == "stt"
    assert items[0]["service"] == "cf-stt"
    assert items[0]["adapter"] is None


def test_installed_finetuned_model_defaults_to_avocet_service(client):
    """Fine-tuned models with no role/service in training_info default to avocet/classifier."""
    from app import models as models_module

    model_dir = models_module._MODELS_DIR / "my-finetuned-v2"
    model_dir.mkdir()
    (model_dir / "training_info.json").write_text(
        json.dumps({"base_model": "microsoft/deberta-v3-base", "epochs": 3}),
        encoding="utf-8",
    )

    r = client.get("/api/models/installed")
    assert r.status_code == 200
    items = r.json()
    assert items[0]["role"] == "classifier"
    assert items[0]["service"] == "avocet"


def test_installed_detects_finetuned_model(client):
    """A subdir with training_info.json is surfaced as type='finetuned'."""
    from app import models as models_module

    model_dir = models_module._MODELS_DIR / "my-finetuned"
    model_dir.mkdir()
    (model_dir / "training_info.json").write_text(
        json.dumps({"base_model": "org/base", "epochs": 5}), encoding="utf-8"
    )

    r = client.get("/api/models/installed")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["type"] == "finetuned"
    assert items[0]["name"] == "my-finetuned"


# ── DELETE /installed/{name} ───────────────────────────────────────────────────

def test_delete_installed_removes_directory(client):
    """DELETE /installed/{name} removes the directory and returns {ok: true}."""
    from app import models as models_module

    model_dir = models_module._MODELS_DIR / "org--removeme"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")

    r = client.delete("/api/models/installed/org--removeme")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert not model_dir.exists()


def test_delete_installed_not_found_returns_404(client):
    r = client.delete("/api/models/installed/does-not-exist")
    assert r.status_code == 404


def test_delete_installed_path_traversal_blocked(client):
    """DELETE /installed/../../etc must be blocked.
    Path traversal normalises to a different URL (/api/etc); if web/dist exists
    the StaticFiles mount intercepts it and returns 405 (GET/HEAD only).
    """
    r = client.delete("/api/models/installed/../../etc")
    assert r.status_code in (400, 404, 405, 422)


def test_delete_installed_dotdot_name_blocked(client):
    """A name containing '..' in any form must be rejected."""
    r = client.delete("/api/models/installed/..%2F..%2Fetc")
    assert r.status_code in (400, 404, 405, 422)


def test_delete_installed_name_with_slash_blocked(client):
    """A name containing a literal '/' after URL decoding must be rejected."""
    from app import models as models_module

    # The router will see the path segment after /installed/ — a second '/' would
    # be parsed as a new path segment, so we test via the validation helper directly.
    with pytest.raises(Exception):
        # Simulate calling delete logic with a slash-containing name directly
        from fastapi import HTTPException as _HTTPException
        from app.models import delete_installed
        try:
            delete_installed("org/traversal")
        except _HTTPException as exc:
            assert exc.status_code in (400, 404)
            raise
