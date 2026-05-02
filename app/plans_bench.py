"""Avocet -- Plans benchmark integration API (stub).

Placeholder module so that app/eval/cforch.py can import and include
this router. Full implementation follows in a subsequent task.

All endpoints are registered on `router` (a FastAPI APIRouter).
api.py (via the eval aggregator) includes this router at
prefix="/api/plans-bench".
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_CONFIG_DIR: Path | None = None   # override in tests via set_config_dir()


def set_config_dir(path: Path | None) -> None:
    """Override config directory -- used by tests."""
    global _CONFIG_DIR
    _CONFIG_DIR = path


@router.get("/status")
def get_plans_bench_status() -> dict:
    """Return placeholder status for the plans benchmark module."""
    return {"status": "not_implemented"}
