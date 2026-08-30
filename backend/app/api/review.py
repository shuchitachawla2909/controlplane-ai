from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_session
from app.api.io import ReviewRequest
from app.controlplane.learning import validate_case
from app.core.models import DecisionRow, ReviewCaseRow, TraceRow

router = APIRouter(prefix="/api", tags=["review"])


@router.get("/review-queue")
def review_queue(status: str = "pending", session: Session = Depends(get_session)):
    stmt = select(ReviewCaseRow).order_by(ReviewCaseRow.created_at.desc())
    if status != "all":
        stmt = stmt.where(ReviewCaseRow.status == status)
    out = []
    for c in session.exec(stmt).all():
        trace = session.get(TraceRow, c.trace_id)
        decision = session.exec(
            select(DecisionRow).where(DecisionRow.trace_id == c.trace_id)
        ).first()
        out.append({
            "case_id": c.case_id,
            "trace_id": c.trace_id,
            "workflow": c.workflow,
            "created_at": c.created_at,
            "status": c.status,
            "reason": c.reason,
            "suggested_labels": c.suggested_labels,
            "request_preview": trace.request_preview if trace else "",
            "response_preview": trace.response_preview if trace else "",
            "action": decision.action if decision else None,
            "overall_risk": decision.overall_risk if decision else None,
            "validator_verdict": c.validator_verdict,
        })
    return out


@router.post("/review/{case_id}")
def submit_review(case_id: str, req: ReviewRequest, session: Session = Depends(get_session)):
    try:
        result = validate_case(session, case_id, verdict=req.verdict, comment=req.comment,
                               authoritative=req.authoritative)
    except KeyError:
        raise HTTPException(404, "review case not found")
    return result | {
        "note": "Validated evidence is now eligible for the learning loop; "
                "a trusted failure pattern can change routing on later similar traces.",
    }
