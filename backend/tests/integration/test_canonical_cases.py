"""The four canonical cases that must work before scaling (clarification #11):
confidently wrong, PII, cost runaway, no ground truth.

Decisions are computed by the real pipeline — nothing is hard-coded per case.
"""
from __future__ import annotations

import pytest

from app.controlplane.baselines import BaselineProvider
from app.controlplane.pipeline import evaluate_trace
from app.controlplane.router import check_agent_step
from app.core.schemas import Action
from tests.factories import (
    confidently_wrong_trace,
    cost_runaway_trace,
    no_ground_truth_trace,
    normal_trace,
    pii_leak_trace,
)


def _cs_baselines() -> BaselineProvider:
    bp = BaselineProvider("customer_support")
    bp.seed_many(normal_trace() for _ in range(40))
    return bp


@pytest.mark.asyncio
async def test_confidently_wrong_is_caught_and_corrected():
    result = await evaluate_trace(confidently_wrong_trace(), baselines=_cs_baselines())
    rec = result.record

    assert rec.performance_risk >= 0.7
    assert rec.performance_confidence >= 0.7
    assert "authoritative_contradiction" in [f.label for f in result.findings]
    assert rec.action in {Action.MODIFY, Action.VERIFY, Action.BLOCK, Action.HUMAN_REVIEW}
    if rec.action == Action.MODIFY:
        assert rec.modification_method == "trusted_source_reconstruction"
        assert "30 days" in rec.safe_response
    assert "60" not in rec.safe_response or rec.action != Action.MODIFY


@pytest.mark.asyncio
async def test_pii_leak_triggers_responsibility_intervention():
    result = await evaluate_trace(pii_leak_trace())
    rec = result.record

    assert rec.responsibility_risk >= 0.7
    assert rec.action in {Action.MODIFY, Action.BLOCK, Action.HUMAN_REVIEW}
    # the safe response must not contain the raw phone/email
    assert "john.smith@example.com" not in rec.safe_response
    assert "98765 43210" not in rec.safe_response
    assert rec.response_modified is True


@pytest.mark.asyncio
async def test_no_ground_truth_reduces_confidence_not_truth():
    result = await evaluate_trace(no_ground_truth_trace())
    rec = result.record

    assert rec.ground_truth_available is False
    assert rec.evidence_confidence < 0.5           # explicitly low
    assert rec.performance_risk >= 0.35
    assert rec.action in {Action.SAFE_FALLBACK, Action.HUMAN_REVIEW}
    # we must NOT have asserted the answer is false
    assert "hallucinat" not in " ".join(rec.reasons).lower()
    assert any("ground truth" in r.lower() for r in rec.reasons + [rec.how_confident])


@pytest.mark.asyncio
async def test_no_ground_truth_judge_cannot_override_uncertainty_after_tier2():
    """Scenario D: even after Tier 2 runs, the surfaced state stays
    'no ground truth' — a judge with nothing to check against is capped."""
    from app.seed.scenarios import SCENARIOS

    result = await evaluate_trace(SCENARIOS["D"].build())
    rec = result.record

    perf = [f for f in result.findings if f.dimension.value == "performance"]
    top = max(perf, key=lambda f: f.score)
    assert top.label == "no_ground_truth"          # NOT judge_unsupported / unsupported
    for f in perf:
        if f.evaluator.startswith("llm_judge"):
            assert f.score <= 0.5 and f.confidence <= 0.3
            assert not f.label.startswith("judge_unsupported")
    assert rec.evidence_confidence < 0.5
    assert rec.action in {Action.SAFE_FALLBACK, Action.HUMAN_REVIEW}


@pytest.mark.asyncio
async def test_evaluation_no_ground_truth_cases_are_clean():
    """Every no_ground_truth case in the balanced dataset must actually have
    NO retrieval context and produce the no_ground_truth label (P0-1)."""
    from app.evaluators.grounding import GroundingEvaluator
    from app.evaluators.base import EvalContext
    from app.seed.data import generate_balanced

    ge = GroundingEvaluator()
    n = ok = 0
    for tr in generate_balanced(seed=4242):
        if tr.metadata["truth"]["category"] != "no_ground_truth":
            continue
        n += 1
        assert not tr.retrieved_context
        assert not tr.authoritative_facts
        assert not any(s.retrieved_context for s in tr.steps)
        r = await ge.evaluate(EvalContext(trace=tr, policy={}, workflow_profile={}))
        ok += int(r.label == "no_ground_truth" and r.confidence <= 0.3)
    assert n == 20 and ok == 20


@pytest.mark.asyncio
async def test_cost_runaway_stops_execution_before_budget_breach():
    bp = BaselineProvider("agent_operations")
    # prime a cheap-normal baseline for the agent workflow
    for _ in range(30):
        t = normal_trace()
        t.workflow = "agent_operations"
        t.estimated_cost_usd = 0.03
        bp.observe_trace(t)

    trace = cost_runaway_trace(in_flight=True)
    gate = await check_agent_step(trace, baselines=bp)
    assert gate.directive == "STOP"
    assert gate.projected_cost_usd > gate.budget_usd

    result = await evaluate_trace(trace, baselines=bp)
    rec = result.record
    assert rec.cost_risk >= 0.7
    assert rec.action == Action.STOP_EXECUTION
    assert rec.execution_stopped is True
    assert rec.prevented_spend_usd > 0
