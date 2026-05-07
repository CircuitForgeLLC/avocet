"""Avocet -- eval router aggregator.

Collects benchmark sub-routers into a single importable `router`
for the api.py factory. Each sub-router retains its established prefix
so no frontend URL changes are needed.

Route prefixes when mounted at /api in api.py:
  /api/cforch/*      -- cf-orch benchmark routes
  /api/style/*       -- writing style benchmark routes
  /api/voice/*       -- voice benchmark routes
  /api/plans-bench/* -- plans benchmark routes
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.cforch import router as _cforch_router
from app.style import router as _style_router
from app.voice import router as _voice_router
from app.plans_bench import router as _plans_router
from app.eval.embed_bench import router as _embed_router

router = APIRouter()
router.include_router(_cforch_router, prefix="/cforch")
router.include_router(_style_router, prefix="/style")
router.include_router(_voice_router, prefix="/voice")
router.include_router(_plans_router, prefix="/plans-bench")
router.include_router(_embed_router, prefix="/embed-bench")


def set_config_dir(path: Path | None) -> None:
    """Propagate config dir override to all sub-modules -- used by tests."""
    import app.cforch as _cforch_mod
    import app.style as _style_mod
    import app.voice as _voice_mod
    import app.plans_bench as _plans_mod
    import app.eval.embed_bench as _embed_mod
    _cforch_mod.set_config_dir(path)
    _style_mod.set_config_dir(path)
    _voice_mod.set_config_dir(path)
    _plans_mod.set_config_dir(path)
    _embed_mod.set_config_dir(path)
