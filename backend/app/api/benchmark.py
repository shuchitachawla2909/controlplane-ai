from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_session
from app.api.io import BenchmarkRequest
from app.controlplane.benchmark import run_benchmark
from app.core.config import get_settings
from app.core.models import BenchmarkRunRow

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


@router.post("/run")
async def benchmark_run(req: BenchmarkRequest, session: Session = Depends(get_session)):
    seed = req.seed if req.seed is not None else get_settings().seed
    result = await run_benchmark(
        count=req.count, seed=seed, profile=req.profile,
        deep_eval_sim_latency_ms=req.deep_eval_sim_latency_ms,
    )
    row = BenchmarkRunRow(
        run_id=f"bench_{uuid.uuid4().hex[:10]}",
        created_at=time.time(),
        label=req.label or result["label"],
        count=req.count,
        arms=result["arms"],
        north_star=result["north_star"],
        params={
            "seed": seed, "profile": req.profile,
            "deep_eval_sim_latency_ms": req.deep_eval_sim_latency_ms,
            "structural": result["structural"],
            "runtime_local": result["runtime_local"],
            "simulated_cost": result["simulated_cost"],
        },
    )
    session.add(row)
    return {"run_id": row.run_id, **result}


@router.get("/results")
def benchmark_results(session: Session = Depends(get_session), limit: int = 10):
    rows = session.exec(
        select(BenchmarkRunRow).order_by(BenchmarkRunRow.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "run_id": r.run_id, "created_at": r.created_at, "label": r.label,
            "count": r.count, "arms": r.arms, "north_star": r.north_star, "params": r.params,
        }
        for r in rows
    ]
