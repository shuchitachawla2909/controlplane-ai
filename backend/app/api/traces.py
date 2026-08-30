from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api.deps import get_session
from app.api.io import EvaluateRequest, IngestTraceRequest
from app.controlplane.pipeline import ingest_and_evaluate
from app.core.models import DecisionRow, TraceRow

router = APIRouter(prefix="/api", tags=["traces"])


@router.post("/traces")
async def ingest_trace(req: IngestTraceRequest, session: Session = Depends(get_session)):
    """Ingest an AI execution trace and run the full ControlPlane pipeline."""
    result = await ingest_and_evaluate(req.trace, session)
    return {"trace_id": req.trace.trace_id, "decision": result.record.model_dump(mode="json")}


@router.post("/evaluate")
async def evaluate_trace_endpoint(req: EvaluateRequest, session: Session = Depends(get_session)):
    result = await ingest_and_evaluate(
        req.trace, session, persist=req.persist, enable_llm_judge=req.enable_llm_judge
    )
    return {
        "decision": result.record.model_dump(mode="json"),
        "risk": result.risk.model_dump(mode="json"),
        "routing": result.routing.model_dump(mode="json"),
    }


@router.get("/traces")
def list_traces(
    session: Session = Depends(get_session),
    limit: int = Query(100, le=500),
    offset: int = 0,
    workflow: str | None = None,
    action: str | None = None,
    min_risk: float | None = None,
):
    stmt = select(DecisionRow).order_by(DecisionRow.created_at.desc())
    if workflow:
        stmt = stmt.where(DecisionRow.workflow == workflow)
    if action:
        stmt = stmt.where(DecisionRow.action == action)
    if min_risk is not None:
        stmt = stmt.where(DecisionRow.overall_risk >= min_risk)
    rows = session.exec(stmt.offset(offset).limit(limit)).all()
    return [
        {
            "decision_id": r.decision_id,
            "trace_id": r.trace_id,
            "created_at": r.created_at,
            "application": r.application,
            "workflow": r.workflow,
            "action": r.action,
            "tier": r.tier,
            "severity": r.severity,
            "overall_risk": r.overall_risk,
            "performance_risk": r.performance_risk,
            "cost_risk": r.cost_risk,
            "responsibility_risk": r.responsibility_risk,
            "evidence_confidence": r.evidence_confidence,
            "controlplane_overhead_ms": r.controlplane_overhead_ms,
            "synchronous": r.synchronous,
            "requires_human_review": r.requires_human_review,
            "policy_version": r.policy_version,
        }
        for r in rows
    ]


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, session: Session = Depends(get_session)):
    trace = session.get(TraceRow, trace_id)
    if trace is None:
        raise HTTPException(404, "trace not found")
    decision = session.exec(
        select(DecisionRow).where(DecisionRow.trace_id == trace_id).order_by(DecisionRow.created_at.desc())
    ).first()
    return {
        "trace": {
            "trace_id": trace.trace_id,
            "session_id": trace.session_id,
            "application": trace.application,
            "workflow": trace.workflow,
            "model": trace.model,
            "provider": trace.provider,
            "created_at": trace.created_at,
            "turn_index": trace.turn_index,
            "request_preview": trace.request_preview,
            "response_preview": trace.response_preview,
            "latency_ms": trace.latency_ms,
            "estimated_cost_usd": trace.estimated_cost_usd,
            "model_calls": trace.model_calls,
            "tool_calls": trace.tool_calls,
            "retrieval_events": trace.retrieval_events,
            "retries": trace.retries,
            "ground_truth_available": trace.ground_truth_available,
            "steps": trace.steps,
        },
        "decision": decision.record if decision else None,
    }
