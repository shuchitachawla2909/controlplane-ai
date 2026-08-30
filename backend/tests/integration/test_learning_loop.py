"""Clarification #4: validated historical evidence must change the routing of a
later, similar interaction — not just sit in storage.

    borderline trace -> fast path ALLOW
      -> user thumbs-down -> review case
      -> human validation -> trusted failure pattern
      -> similar trace later -> deep verification / escalation
"""
from __future__ import annotations

import pytest

from app.controlplane.baselines import BaselineProvider
from app.controlplane.learning import (
    FeedbackInput,
    load_learning_context,
    record_feedback,
    validate_case,
)
from app.controlplane.pipeline import ingest_and_evaluate
from app.core.models import ReviewCaseRow
from app.core.schemas import AITrace, StepType, TraceStep, Usage
from sqlmodel import select


def _returns_trace() -> AITrace:
    ctx = ["Refunds for returned items are handled case by case by the support team after a request is raised."]
    return AITrace(
        application="Customer Support Assistant", workflow="customer_support", model="mock-model",
        request_text="If I change my mind about a purchase, can I send it back for a refund?",
        response_text="Refunds for returned items are handled case by case by the support team after a request is raised.",
        retrieved_context=ctx, evidence_expected=True,
        steps=[TraceStep(type=StepType.RETRIEVAL, name="kb", duration_ms=100, retrieved_context=ctx),
               TraceStep(type=StepType.FINAL_RESPONSE, model="mock-model",
                         usage=Usage(input_tokens=200, output_tokens=80), duration_ms=600)],
    )


@pytest.mark.asyncio
async def test_validated_evidence_changes_future_routing(db_session):
    bp = BaselineProvider("customer_support", db_session)
    from app.seed.data import generate
    for tr in generate(300, seed=11):
        if tr.workflow == "customer_support" and tr.metadata.get("truth", {}).get("category") == "normal":
            bp.observe_trace(tr)
    bp.persist()
    db_session.flush()

    # 1. BEFORE learning: borderline trace stays on the fast path.
    t1 = _returns_trace()
    r1 = await ingest_and_evaluate(t1, db_session, update_baseline=False)
    db_session.flush()
    assert r1.record.action.value in {"ALLOW", "MONITOR"}
    assert 2 not in r1.record.tiers_run
    assert not load_learning_context(db_session, "customer_support").trusted_failure_patterns

    # 2. User reports it, a reviewer confirms it was wrong.
    record_feedback(db_session, FeedbackInput(trace_id=t1.trace_id, thumbs="down", reason="incorrect"))
    db_session.flush()
    case = db_session.exec(select(ReviewCaseRow).where(ReviewCaseRow.trace_id == t1.trace_id)).first()
    assert case is not None
    outcome = validate_case(db_session, case.case_id, verdict="incorrect",
                            comment="Return window is 30 days; answer was too vague/incorrect.")
    db_session.flush()
    assert outcome["pattern_status"] == "trusted"

    # 3. AFTER learning: a NEW, similar interaction is now routed deeper.
    patterns = load_learning_context(db_session, "customer_support").trusted_failure_patterns
    assert patterns and patterns[0]["signature"] == "customer_support:return_policy"

    t2 = _returns_trace()
    r2 = await ingest_and_evaluate(t2, db_session, update_baseline=False)

    # routing genuinely changed: risk rose, and the interaction is no longer on
    # the plain fast-path ALLOW — it is either deep-checked or acted on.
    assert r2.record.performance_risk > r1.record.performance_risk + 0.2
    assert r2.record.action.value != "ALLOW"
    assert (2 in r2.record.tiers_run) or r2.record.action.value in {
        "VERIFY", "HUMAN_REVIEW", "SAFE_FALLBACK", "MODIFY", "BLOCK", "MONITOR"
    }
    assert r2.record.verification_value > r1.record.verification_value
    assert any("validated failure pattern" in " ".join(f.reasons).lower() for f in r2.findings)
