"""
Avocet cloud session — thin wrapper around cf_core.cloud_session.

Usage in FastAPI routes:

    from app.cloud_session import get_session, require_tier, CloudUser
    from fastapi import Depends

    @router.get("/api/imitate")
    def imitate(session: CloudUser = Depends(get_session)):
        # session.user_id  — Directus UUID (cloud) or "local" (self-hosted)
        # session.tier     — free | paid | premium | ultra | local
        # session.has_byok — True if user has a configured LLM backend
        ...

    @router.post("/api/custom-models")
    def list_custom_models(session: CloudUser = Depends(require_tier("premium"))):
        ...
"""
from __future__ import annotations

import os

from circuitforge_core.cloud_session import CloudSessionFactory, CloudUser, detect_byok

__all__ = ["CloudUser", "get_session", "require_tier"]

_factory = CloudSessionFactory(
    product="avocet",
    byok_detector=detect_byok,
)

get_session = _factory.dependency()
require_tier = _factory.require_tier
