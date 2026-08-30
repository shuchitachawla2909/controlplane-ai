"""ControlPlane.ai API.

Adaptive Runtime AI Oversight — observe every AI execution cheaply, investigate
selectively, act proportionally, learn continuously.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import benchmark, demo, feedback, metrics, policies, review, traces
from app.core.config import get_settings
from app.core.database import init_db, session_scope

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as s:
        policies.sync_policies_to_db(s)
    if settings.seed_on_boot:
        from sqlmodel import select

        from app.core.models import DecisionRow
        from app.seed.runner import seed_everything

        with session_scope() as s:
            if not s.exec(select(DecisionRow).limit(1)).first():
                await seed_everything(s, count=1200, fresh=False)
    yield


app = FastAPI(
    title="ControlPlane.ai",
    version="0.1.0",
    summary="Adaptive runtime AI oversight layer — Accenture Innovation Challenge 2026 (Round 2 prototype).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (traces.router, feedback.router, review.router, policies.router,
          metrics.router, demo.router, benchmark.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"status": "ok", "demo_mode": settings.demo_mode, "llm_provider": settings.llm_provider}


@app.get("/")
def root():
    return {
        "name": "ControlPlane.ai",
        "positioning": "Adaptive Runtime AI Oversight",
        "principle": "Observe everything. Investigate selectively. Act proportionally. Learn continuously.",
        "docs": "/docs",
        "health": "/health",
    }
