from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session
from app.api.io import FeedbackRequest
from app.controlplane.learning import FeedbackInput, record_feedback

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/feedback")
def submit_feedback(req: FeedbackRequest, session: Session = Depends(get_session)):
    ev = record_feedback(
        session,
        FeedbackInput(trace_id=req.trace_id, thumbs=req.thumbs, reason=req.reason,
                      comment=req.comment, source=req.source),
    )
    return {
        "evidence_id": ev.evidence_id,
        "trust_level": ev.trust_level,
        "pattern_signature": ev.pattern_signature,
        "duplicate_of": ev.duplicate_of,
        "note": "Feedback stored as evidence. Raw feedback cannot change critical behaviour on its own (§49).",
    }
