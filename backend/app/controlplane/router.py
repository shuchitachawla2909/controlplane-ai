"""Tier router — the adaptive funnel (§6, §24, §26).

    Tier 0 observe  ->  Tier 1 cheap checks (parallel)  ->  risk engine
      -> route(): fast path? verify? escalate?
      -> [Tier 2 selective verification]  ->  policy.decide()  ->  intervention

Normal low-risk traffic never touches Tier 2, so deep evaluation stays off the
critical path. High-risk traffic is handled synchronously so ControlPlane can
act before the response reaches the user (clarification #2).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.controlplane import interventions, risk_engine
from app.controlplane.baselines import BaselineProvider
from app.controlplane.cost_model import project_final_cost
from app.controlplane.policy_engine import PolicyStore, decide, get_policy_store, route
from app.controlplane.observer import observe
from app.evaluators.base import EvalContext, Evaluator
from app.evaluators.registry import deep_evaluators_for, tier1_evaluators
from app.core.schemas import (
    Action,
    AITrace,
    DecisionRecord,
    Dimension,
    EvaluationResult,
    RiskSummary,
    RoutingDecision,
)


@dataclass
class LearningContext:
    """Read-only view the router needs from the learning store."""

    trusted_failure_patterns: list[dict[str, Any]] = field(default_factory=list)
    prior_evidence: list = field(default_factory=list)


@dataclass
class PipelineResult:
    record: DecisionRecord
    risk: RiskSummary
    routing: RoutingDecision
    findings: list[EvaluationResult]
    tier1_findings: list[EvaluationResult]
    tier2_findings: list[EvaluationResult] = field(default_factory=list)


async def _run_dispatch(evaluators: list[Evaluator], ctx: EvalContext) -> tuple[list[EvaluationResult], float, float]:
    """Dispatch independent checks together via ``asyncio.gather``.

    The Tier-1 checks are deterministic CPU work (regex / arithmetic); measured
    end-to-end they run in ~0.1 ms for all 7, so gather is a *scheduling*
    convenience, not a speed-up — we do NOT claim parallel execution makes the
    fast path faster. Concurrency matters for Tier 2, where an evaluator may do
    real I/O (an external LLM judge, a Presidio service). Threading the Tier-1
    checks was measured and is slower (task-creation overhead > the work), so we
    keep it simple.

    Returns (results, dispatch_wall_ms, summed_check_ms).
    """
    start = time.perf_counter()
    results = await asyncio.gather(*(e.evaluate(ctx) for e in evaluators))
    dispatch_wall_ms = (time.perf_counter() - start) * 1000
    summed_check_ms = sum(r.latency_ms for r in results)
    return list(results), dispatch_wall_ms, summed_check_ms


def _uncertain_dimensions(risk: RiskSummary, routing: RoutingDecision) -> set[Dimension]:
    dims: set[Dimension] = set()
    for dr in (risk.performance, risk.responsibility):
        if dr.risk >= 0.3 or (dr.risk >= 0.2 and dr.confidence < 0.55):
            dims.add(dr.dimension)
    if not dims:                       # escalated with nothing specific -> verify performance
        dims.add(Dimension.PERFORMANCE)
    return dims


async def run_pipeline(
    trace: AITrace,
    *,
    policy_store: PolicyStore | None = None,
    learning: LearningContext | None = None,
    baselines: BaselineProvider | None = None,
    enable_llm_judge: bool = True,
    force_deep: bool = False,          # benchmark arm B ("always deep")
) -> PipelineResult:
    t0 = time.perf_counter()
    policy_store = policy_store or get_policy_store()
    learning = learning or LearningContext()

    # ---- Tier 0 -------------------------------------------------------
    observe(trace)
    policy = policy_store.resolve(trace.workflow)
    if baselines is None:
        baselines = BaselineProvider(trace.workflow)

    ctx = EvalContext(
        trace=trace,
        policy=policy.body,
        workflow_profile=policy.profile,
        tier=1,
        prior_evidence=learning.prior_evidence,
        trusted_failure_patterns=learning.trusted_failure_patterns,
        baseline_lookup=baselines,
        llm_provider=_provider(),
    )

    # ---- Tier 1: independent cheap checks, dispatched together ------
    t1_findings, parallel_ms, sequential_ms = await _run_dispatch(tier1_evaluators(), ctx)
    risk = risk_engine.assess(trace, t1_findings, policy.profile, baselines)
    routing = route(risk, policy)

    expected_cost = 0.0
    if baselines is not None:
        cb = baselines.get("cost_usd")
        expected_cost = cb.median if cb.n else 0.0
    projected_cost, _traj = project_final_cost(trace, expected_cost or None)

    tiers_run = [0, 1]
    t2_findings: list[EvaluationResult] = []
    all_findings = list(t1_findings)
    synchronous = True

    run_deep = force_deep or routing.verify or (
        routing.escalate and _needs_evidence(risk) and not _already_corroborated(risk)
    )
    if run_deep:
        ctx.tier = 2
        dims = {Dimension.PERFORMANCE, Dimension.RESPONSIBILITY} if force_deep else _uncertain_dimensions(risk, routing)
        deep = deep_evaluators_for(dims, enable_llm_judge=enable_llm_judge)
        if deep:
            t2_findings, p2, s2 = await _run_dispatch(deep, ctx)
            parallel_ms += p2
            sequential_ms += s2
            all_findings += t2_findings
            tiers_run.append(2)
            risk = risk_engine.assess(trace, all_findings, policy.profile, baselines)
        synchronous = not routing.async_deep_eval

    tier2_done = 2 in tiers_run
    outcome = decide(
        risk,
        all_findings,
        policy,
        tier2_done=tier2_done,
        projected_cost=projected_cost,
        expected_cost=expected_cost,
        in_flight=trace.in_flight,
    )

    # Async deep-eval path: the user already had the response; keep the light
    # action but attach the deep findings as after-the-fact evidence.
    if routing.async_deep_eval and outcome.action in {Action.VERIFY}:
        from app.controlplane.policy_engine import DecisionOutcome

        outcome = DecisionOutcome(action=Action.MONITOR,
                                  reasons=[*outcome.reasons, "Deep evaluation ran asynchronously after disclosure."])

    overhead_ms = (time.perf_counter() - t0) * 1000
    record = interventions.build_decision_record(
        trace, risk, all_findings, routing, outcome, policy,
        tiers_run=tiers_run,
        timings={"overhead_ms": overhead_ms, "sequential_ms": sequential_ms, "parallel_ms": parallel_ms},
        projected_cost=projected_cost,
        expected_cost=expected_cost,
        synchronous=synchronous,
    )
    record.tier = max(tiers_run)
    return PipelineResult(
        record=record, risk=risk, routing=routing,
        findings=all_findings, tier1_findings=t1_findings, tier2_findings=t2_findings,
    )


def _needs_evidence(risk: RiskSummary) -> bool:
    # Escalations driven by a performance contradiction benefit from Tier 2
    # corroboration; pure responsibility/cost escalations act immediately.
    return "authoritative_contradiction" in risk.performance.labels or risk.performance.risk >= 0.6


def _already_corroborated(risk: RiskSummary) -> bool:
    # A trusted, validated failure pattern IS the corroboration — ControlPlane
    # can act without paying for Tier 2 again (this is the learning-loop payoff).
    return (
        "known_failure_pattern" in risk.performance.labels
        and risk.performance.confidence >= 0.65
        and "authoritative_contradiction" not in risk.performance.labels
    )


def _provider() -> str:
    from app.core.config import get_settings

    return get_settings().llm_provider


# ---------------------------------------------------------------------------
# In-flight agent hook (§23, clarification #3)
# ---------------------------------------------------------------------------
@dataclass
class StepDecision:
    directive: str                     # "CONTINUE" | "STOP"
    step_index: int
    cumulative_cost_usd: float
    projected_cost_usd: float
    budget_usd: float
    trajectory: str
    reason: str


async def check_agent_step(
    partial_trace: AITrace,
    *,
    policy_store: PolicyStore | None = None,
    baselines: BaselineProvider | None = None,
) -> StepDecision:
    """Called after each LLM/tool step of a running agent. Cheap and synchronous.

    step -> update cumulative cost -> project trajectory -> CONTINUE or STOP,
    stopping BEFORE the projected cost exceeds the configured budget.
    """
    policy_store = policy_store or get_policy_store()
    partial_trace.in_flight = True
    observe(partial_trace)
    policy = policy_store.resolve(partial_trace.workflow)
    if baselines is None:
        baselines = BaselineProvider(partial_trace.workflow)

    cb = baselines.get("cost_usd")
    expected = cb.median if cb.n else policy.cost_budget_usd / 3.0
    projected, trajectory = project_final_cost(partial_trace, expected)
    budget = policy.cost_budget_usd
    ct = policy.thr("cost")
    current = partial_trace.estimated_cost_usd
    idx = len([s for s in partial_trace.steps if s.type.value != "final_response"])

    stop = (
        current > budget
        or projected > budget
        or (expected and projected >= ct["stop_multiplier"] * expected and trajectory == "rapidly_increasing")
    )
    if stop:
        reason = (
            f"After step {idx}: spent ${current:.3f}, projected ${projected:.3f} vs budget ${budget:.2f} "
            f"(trajectory: {trajectory}). Stopping before the budget is breached."
        )
        return StepDecision("STOP", idx, round(current, 6), round(projected, 6), budget, trajectory, reason)

    return StepDecision(
        "CONTINUE", idx, round(current, 6), round(projected, 6), budget, trajectory,
        f"After step {idx}: ${current:.3f} spent, projected ${projected:.3f}, within budget ${budget:.2f}.",
    )
