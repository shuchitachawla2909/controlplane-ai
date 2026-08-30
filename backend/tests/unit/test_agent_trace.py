"""Agent / multi-step trace behaviour (§21-23)."""
from __future__ import annotations

import pytest

from app.controlplane.baselines import BaselineProvider
from app.controlplane.cost_model import estimate_trace_cost, project_final_cost
from app.controlplane.observer import observe
from app.controlplane.router import check_agent_step
from app.core.schemas import AITrace, StepType, TraceStep, Usage


def _agent(costs, in_flight=True) -> AITrace:
    steps = [TraceStep(type=StepType.LLM_CALL if i % 2 == 0 else StepType.TOOL_CALL,
                       name=f"s{i}", model="mock-model-pro", cost_usd=c, duration_ms=800,
                       retries=1 if i >= 3 else 0)
             for i, c in enumerate(costs)]
    return AITrace(application="x", workflow="agent_operations", request_text="q", response_text="",
                   in_flight=in_flight, steps=steps)


def test_observer_builds_execution_tree_metrics():
    t = _agent([0.01, 0.02, 0.03], in_flight=False)
    t.steps.append(TraceStep(type=StepType.FINAL_RESPONSE, model="mock-model-pro",
                             usage=Usage(input_tokens=10, output_tokens=20), duration_ms=100))
    observe(t)
    assert t.model_calls == 2 and t.tool_calls == 1
    assert t.steps[-2].cumulative_cost_usd > t.steps[0].cumulative_cost_usd
    assert t.estimated_cost_usd == estimate_trace_cost(t)


def test_cost_trajectory_projects_acceleration():
    t = _agent([0.01, 0.02, 0.04, 0.08, 0.15])
    projected, label = project_final_cost(t, expected_cost=0.03)
    assert label == "rapidly_increasing"
    assert projected > t.estimated_cost_usd


@pytest.mark.asyncio
async def test_in_flight_hook_stops_before_budget_breach():
    bp = BaselineProvider("agent_operations")
    for _ in range(30):
        tr = _agent([0.005, 0.004, 0.006], in_flight=False)
        bp.observe_trace(tr)

    # simulate steps arriving one by one
    costs = [0.01, 0.02, 0.04, 0.08, 0.16, 0.3]
    trace = _agent([], in_flight=True)
    stopped_at = None
    for i, c in enumerate(costs):
        trace.steps.append(TraceStep(type=StepType.LLM_CALL, name=f"s{i}", model="mock-model-pro",
                                     cost_usd=c, duration_ms=800, retries=1 if i >= 3 else 0))
        gate = await check_agent_step(trace, baselines=bp)
        if gate.directive == "STOP":
            stopped_at = i
            assert gate.projected_cost_usd <= gate.budget_usd or gate.cumulative_cost_usd <= gate.budget_usd + 0.2
            break
    assert stopped_at is not None and stopped_at < len(costs) - 1  # stopped early


@pytest.mark.asyncio
async def test_inherited_risk_makes_downstream_action_consequential():
    from app.controlplane.pipeline import evaluate_trace

    t = AITrace(application="x", workflow="agent_operations", request_text="execute transfer",
                response_text="Initiating irreversible bank transfer of $8,000.",
                metadata={"inherited_risk": 0.7, "consequential_action": True},
                steps=[TraceStep(type=StepType.TOOL_CALL, name="bank_transfer", cost_usd=0.02, duration_ms=300)])
    r = await evaluate_trace(t)
    assert r.record.impact.value == "high"
    assert r.record.action.value in {"HUMAN_REVIEW", "SAFE_FALLBACK", "BLOCK", "VERIFY"}
