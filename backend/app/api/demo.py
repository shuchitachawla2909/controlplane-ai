from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import get_session
from app.controlplane.baselines import BaselineProvider
from app.controlplane.pipeline import ingest_and_evaluate, persist_result
from app.controlplane.sessions import evaluate_session
from app.seed.scenarios import SCENARIOS, list_scenarios

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/scenarios")
def scenarios():
    return list_scenarios()


@router.post("/run/{key}")
async def run_scenario(key: str, session: Session = Depends(get_session)):
    key = key.upper()
    if key not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario '{key}'")
    sc = SCENARIOS[key]
    built = sc.build()

    if sc.multi_turn:
        turns = built
        result = await evaluate_session(turns, baselines=BaselineProvider(sc.workflow, session))
        for turn, pr in zip(turns, result.turns):
            persist_result(session, turn, pr)
        return {
            "scenario": key,
            "title": sc.title,
            "multi_turn": True,
            "inherited_risk_trace": result.inherited_trace,
            "turns": [pr.record.model_dump(mode="json") for pr in result.turns],
            "expected": sc.expected,
        }

    trace = built
    result = await ingest_and_evaluate(trace, session)
    return {
        "scenario": key,
        "title": sc.title,
        "multi_turn": False,
        "trace_id": trace.trace_id,
        "decision": result.record.model_dump(mode="json"),
        "risk": result.risk.model_dump(mode="json"),
        "routing": result.routing.model_dump(mode="json"),
        "expected": sc.expected,
    }


@router.post("/seed")
async def seed_demo(count: int = 1500, session: Session = Depends(get_session)):
    """Populate the dashboard with synthetic history + the 7 curated scenarios."""
    from app.seed.runner import seed_everything

    return await seed_everything(session, count=count)
