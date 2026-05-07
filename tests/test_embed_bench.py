"""Tests for app/eval/embed_bench.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_embed_bench_globals(tmp_path):
    """Redirect config dir to tmp_path and reset running flag."""
    from app.eval import embed_bench as mod

    prev_config_dir = mod._CONFIG_DIR
    prev_running = mod._RUN_ACTIVE

    mod.set_config_dir(tmp_path)
    mod._RUN_ACTIVE = False

    yield tmp_path

    mod.set_config_dir(prev_config_dir)
    mod._RUN_ACTIVE = prev_running


@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


# ── cosine helper ──────────────────────────────────────────────────────────────

def test_cosine_identical():
    from app.eval.embed_bench import _cosine
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal():
    from app.eval.embed_bench import _cosine
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite():
    from app.eval.embed_bench import _cosine
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_zero_vector_returns_zero():
    from app.eval.embed_bench import _cosine
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
