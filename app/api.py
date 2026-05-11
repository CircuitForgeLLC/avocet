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

from app.plans_bench import router as plans_bench_router
app.include_router(plans_bench_router, prefix="/api/plans-bench")

# In-memory last-action store (single user, local tool — in-memory is fine)
_last_action: dict | None = None

# -- Backward-compat shims (ClassifierTab still uses old /api/finetune/* paths)
# Remove once ClassifierTab fine-tune section is migrated to TrainJobsView.

from fastapi import Query
from fastapi.responses import StreamingResponse as _StreamingResponse

@app.get("/api/finetune/run")
def finetune_run_compat(model: str = Query(...), epochs: int = Query(5)) -> _StreamingResponse:
    """Shim: create a classifier train job and immediately stream it."""
    from app.train.train import create_job, run_job, CreateJobRequest
    job = create_job(CreateJobRequest(type="classifier", model_key=model, config_json={"epochs": epochs}))
    return run_job(job["id"])

@app.post("/api/finetune/cancel")
def finetune_cancel_compat() -> dict:
    """Shim: cancel the most recent running classifier job."""
    from app.train.train import _db, _init_db, cancel_job
    from fastapi import HTTPException
    _init_db()
    with _db() as conn:
        row = conn.execute(
            "SELECT id FROM jobs WHERE type='classifier' AND status='running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {"status": "nothing_running"}
    return cancel_job(row["id"])

from app.dashboard import router as dashboard_router
app.include_router(dashboard_router, prefix="/api")

from app.models import router as models_router
app.include_router(models_router, prefix="/api/models")

from app.nodes import router as nodes_router
app.include_router(nodes_router, prefix="/api/nodes-mgmt")

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
