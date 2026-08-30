"""ConflictingEvidenceEvaluator — must fire on genuine conflicts and stay
silent on ordinary non-conflicting multi-chunk retrieval (§48 alert fatigue)."""
from __future__ import annotations

import pytest

from app.evaluators.conflicting_evidence import ConflictingEvidenceEvaluator
from app.evaluators.base import EvalContext
from app.core.schemas import AITrace, StepType, TraceStep


def _ctx(context: list[str], signals: list[str] | None = None) -> EvalContext:
    steps = [TraceStep(type=StepType.RETRIEVAL, name="kb", duration_ms=100,
                       retrieved_context=context, risk_signals=signals or []),
             TraceStep(type=StepType.FINAL_RESPONSE, model="mock-model", duration_ms=200)]
    tr = AITrace(application="x", workflow="agent_operations", request_text="q",
                 response_text="a", retrieved_context=context, evidence_expected=True, steps=steps)
    return EvalContext(trace=tr, policy={}, workflow_profile={})


@pytest.mark.asyncio
async def test_detects_conflicting_numeric_values_for_same_concept():
    r = await ConflictingEvidenceEvaluator().evaluate(_ctx([
        "Vendor SLA (current): refunds above 5000 dollars require director approval.",
        "Vendor SLA (older): refunds are auto-approved up to 10000 dollars without escalation.",
    ]))
    assert r.label == "conflicting_evidence"
    assert 0.35 <= r.score <= 0.6           # MEDIUM
    assert r.confidence <= 0.35             # LOW — evidence unreliable, not the answer
    assert not any("false" in x.lower() or "hallucin" in x.lower() for x in r.reasons)


@pytest.mark.asyncio
async def test_explicit_risk_signal_is_honoured():
    r = await ConflictingEvidenceEvaluator().evaluate(_ctx(
        ["chunk one", "chunk two"], signals=["conflicting_evidence"]))
    assert r.label == "conflicting_evidence"


@pytest.mark.asyncio
async def test_zero_on_consistent_multi_chunk_retrieval():
    r = await ConflictingEvidenceEvaluator().evaluate(_ctx([
        "Support hours are 9am to 6pm Monday to Friday.",
        "Weekend support is handled by email only, with a 24 hour response target.",
        "Phone support is available during business hours on +1 555 0100.",
    ]))
    assert r.score == 0.0 and r.label == "no_conflict"


@pytest.mark.asyncio
async def test_ignores_structural_numbers_like_versions_and_pages():
    r = await ConflictingEvidenceEvaluator().evaluate(_ctx([
        "Policy document version 3, page 12: escalation applies to tier 2 tickets.",
        "Policy document version 1, page 4: escalation applies to tier 2 tickets.",
    ]))
    assert r.score == 0.0


@pytest.mark.asyncio
async def test_zero_on_single_chunk():
    r = await ConflictingEvidenceEvaluator().evaluate(_ctx(["only one chunk, nothing to compare"]))
    assert r.score == 0.0


@pytest.mark.asyncio
async def test_no_false_positive_on_regression_normals():
    """The 62 clean-normal evaluation cases must not trip conflicting evidence."""
    from app.seed.data import generate_balanced

    ev = ConflictingEvidenceEvaluator()
    tripped = 0
    for tr in generate_balanced(seed=4242):
        if tr.metadata["truth"]["category"] != "normal":
            continue
        ctx = EvalContext(trace=tr, policy={}, workflow_profile={})
        if (await ev.evaluate(ctx)).score > 0:
            tripped += 1
    assert tripped == 0
