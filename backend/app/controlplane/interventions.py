"""Tier 3 — proportional intervention (§9, §28, §29, §58).

Turns a :class:`DecisionOutcome` into the response the downstream consumer
actually receives, plus the human-readable explainability fields.

MODIFY never calls another model — it applies the deterministic remediation
already proposed by an evaluator (redaction) or the policy engine
(trusted-source reconstruction / safe fallback).
"""
from __future__ import annotations

from app.controlplane.policy_engine import DecisionOutcome, ResolvedPolicy
from app.core.schemas import (
    Action,
    AITrace,
    DecisionRecord,
    Dimension,
    EvaluationResult,
    RiskSummary,
    RoutingDecision,
)

SAFE_FALLBACK_TEXT = (
    "I could not confidently verify this information against a trusted source. "
    "Please consult the official documentation or ask an authorized reviewer to "
    "confirm it before acting on it."
)
BLOCK_TEXT = (
    "This response was withheld by ControlPlane because it triggered a "
    "high-confidence safety or privacy policy. A safe alternative or human "
    "review is required."
)
HUMAN_REVIEW_TEXT = (
    "This response is held for human review. A reviewer will confirm or correct "
    "it before it is released."
)


def _stop_text(trace: AITrace) -> str:
    done = [s for s in trace.steps if s.type.value != "final_response"]
    return (
        f"Agent execution was stopped by ControlPlane after {len(done)} steps because the "
        f"projected cost exceeded the configured budget. Partial results are retained for review."
    )


def apply(
    outcome: DecisionOutcome,
    trace: AITrace,
    projected_cost: float = 0.0,
) -> dict:
    original = trace.response_text or ""
    modified = False
    method = outcome.modification_method
    stopped = False
    prevented = 0.0
    safe = original

    if outcome.action in (Action.ALLOW, Action.MONITOR, Action.VERIFY):
        safe = original
    elif outcome.action == Action.MODIFY:
        safe = outcome.proposed_safe_response or original
        modified = safe != original
        method = method or "redaction"
    elif outcome.action == Action.SAFE_FALLBACK:
        safe = SAFE_FALLBACK_TEXT
        modified = True
        method = "safe_fallback"
    elif outcome.action == Action.BLOCK:
        safe = BLOCK_TEXT
        modified = True
        method = method or "blocked"
    elif outcome.action == Action.HUMAN_REVIEW:
        safe = HUMAN_REVIEW_TEXT
        modified = True
        method = method or "held_for_review"
    elif outcome.action == Action.STOP_EXECUTION:
        safe = _stop_text(trace)
        modified = True
        stopped = True
        method = "execution_stopped"
        prevented = max(0.0, round(projected_cost - trace.estimated_cost_usd, 6))

    return {
        "original_response": original,
        "safe_response": safe,
        "response_modified": modified,
        "modification_method": method,
        "execution_stopped": stopped,
        "prevented_spend_usd": prevented,
    }


def _confidence_phrase(x: float) -> str:
    if x >= 0.8:
        return f"high ({x:.2f})"
    if x >= 0.55:
        return f"moderate ({x:.2f})"
    if x >= 0.35:
        return f"low ({x:.2f})"
    return f"very low ({x:.2f})"


def explain(
    action: Action,
    risk: RiskSummary,
    findings: list[EvaluationResult],
    outcome: DecisionOutcome,
    intervention: dict,
) -> dict:
    """The five plain-language answers shown in the trace UI (§58)."""
    contributing = [
        f for f in findings
        if f.score >= 0.3 and f.label not in {"ok", "no_pii", "no_bias_signal", "no_known_pattern"}
    ]
    contributing.sort(key=lambda f: f.score, reverse=True)

    if contributing:
        top = contributing[0]
        what = top.reasons[0] if top.reasons else f"{top.dimension.value} risk detected ({top.label})."
        how = "; ".join(r for f in contributing[:3] for r in f.reasons[:1])
        driver_conf = top.confidence
    else:
        what = "No material risk was detected across performance, cost or responsibility."
        how = "All Tier 1 checks returned low risk."
        driver_conf = risk.overall_confidence

    return {
        "what_happened": what,
        "how_detected": how,
        "how_confident": (
            f"Evidence confidence is {_confidence_phrase(driver_conf)}. "
            f"Baseline confidence {_confidence_phrase(risk.baseline_confidence)}; "
            f"ground truth available: {str(risk.ground_truth_available).lower()}."
        ),
        "why_action": " ".join(outcome.reasons) or risk.aggregation_note,
        "what_we_did": {
            Action.ALLOW: "Allowed the original response on the fast path.",
            Action.MONITOR: "Allowed the response and queued an asynchronous deep evaluation.",
            Action.VERIFY: "Ran selective Tier 2 verification before disclosure.",
            Action.MODIFY: f"Replaced the response via {intervention['modification_method']} and released the safe version.",
            Action.BLOCK: "Withheld the response and returned a safe notice.",
            Action.STOP_EXECUTION: (
                f"Stopped agent execution; prevented an estimated "
                f"${intervention['prevented_spend_usd']:.3f} of additional simulated spend."
            ),
            Action.HUMAN_REVIEW: "Routed the case to the human review queue and returned a holding message.",
            Action.SAFE_FALLBACK: "Returned a safe fallback instead of an unverifiable answer.",
        }[action],
    }


def build_decision_record(
    trace: AITrace,
    risk: RiskSummary,
    findings: list[EvaluationResult],
    routing: RoutingDecision,
    outcome: DecisionOutcome,
    policy: ResolvedPolicy,
    *,
    tiers_run: list[int],
    timings: dict,
    projected_cost: float,
    expected_cost: float,
    synchronous: bool,
) -> DecisionRecord:
    intervention = apply(outcome, trace, projected_cost)
    ex = explain(outcome.action, risk, findings, outcome, intervention)

    return DecisionRecord(
        trace_id=trace.trace_id,
        session_id=trace.session_id,
        application=trace.application,
        workflow=trace.workflow,
        policy_name=policy.name,
        policy_version=policy.version,
        performance_risk=risk.performance.risk,
        cost_risk=risk.cost.risk,
        responsibility_risk=risk.responsibility.risk,
        performance_confidence=risk.performance.confidence,
        cost_confidence=risk.cost.confidence,
        responsibility_confidence=risk.responsibility.confidence,
        overall_risk=risk.overall_risk,
        evidence_confidence=risk.overall_confidence,
        severity=max(risk.performance.severity, risk.cost.severity, risk.responsibility.severity,
                     key=lambda s: ["none", "low", "medium", "high", "critical"].index(s.value)),
        impact=risk.impact,
        novelty=risk.novelty,
        ground_truth_available=risk.ground_truth_available,
        tiers_run=tiers_run,
        evaluators_run=[f.evaluator for f in findings],
        verification_value=routing.verification_value,
        action=outcome.action,
        reasons=outcome.reasons,
        what_happened=ex["what_happened"],
        how_detected=ex["how_detected"],
        how_confident=ex["how_confident"],
        why_action=ex["why_action"],
        what_we_did=ex["what_we_did"],
        original_response=intervention["original_response"],
        safe_response=intervention["safe_response"],
        response_modified=intervention["response_modified"],
        modification_method=intervention["modification_method"],
        projected_cost_usd=round(projected_cost, 6),
        cost_budget_usd=policy.cost_budget_usd,
        prevented_spend_usd=intervention["prevented_spend_usd"],
        execution_stopped=intervention["execution_stopped"],
        controlplane_overhead_ms=round(timings.get("overhead_ms", 0.0), 3),
        sequential_check_ms=round(timings.get("sequential_ms", 0.0), 3),
        parallel_check_ms=round(timings.get("parallel_ms", 0.0), 3),
        synchronous=synchronous,
        evidence=[e for f in findings for e in f.evidence],
        findings=findings,
        requires_human_review=outcome.requires_human_review or outcome.action == Action.HUMAN_REVIEW,
    )
