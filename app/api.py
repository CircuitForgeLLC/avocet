"""Avocet -- FastAPI app factory.

Mounts all domain routers and serves the Vue SPA.
All business logic lives in the domain modules below.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

app = FastAPI(title="Avocet API")

# -- Domain routers --------------------------------------------------------

from app.data.label import router as label_router
app.include_router(label_router, prefix="/api")

from app.data.fetch import router as fetch_router
app.include_router(fetch_router, prefix="/api")

from app.data.corrections import router as corrections_router
app.include_router(corrections_router, prefix="/api/corrections")

# Backward-compat alias -- remove when Vue SPA is updated to /api/corrections/*
app.include_router(corrections_router, prefix="/api/sft")

from app.data.imitate import router as imitate_router
app.include_router(imitate_router, prefix="/api/imitate")

from app.eval.cforch import router as eval_router
app.include_router(eval_router, prefix="/api")

from app.train.train import router as train_router
app.include_router(train_router, prefix="/api/train")

from app.dashboard import router as dashboard_router
app.include_router(dashboard_router, prefix="/api")

from app.models import router as models_router
app.include_router(models_router, prefix="/api/models")

# -- Static SPA -- MUST be last (catches all unmatched paths) ---------------

_ROOT = Path(__file__).parent.parent
_DIST = _ROOT / "web" / "dist"
if _DIST.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}

    @app.get("/")
    def get_spa_root():
        return FileResponse(str(_DIST / "index.html"), headers=_NO_CACHE)

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="spa")
