"""Adaptive risk + confidence engine (§10, §61).

Design rules held here:

* performance / cost / responsibility risk stay SEPARATE, and each carries its
  own confidence. The UI always shows the components, never just one number.
* We do NOT average the dimensions. A critical responsibility risk must keep
  overall risk high even if performance and cost are near zero.
* The aggregation is interpretable and documented (also in
  docs/decision_engine.md):

      adjusted[d] = risk[d] x severity_mult[d] x impact_mult x confidence[d]
      overall_risk = max(adjusted[d] for d in dimensions)
      + cross-risk escalation when >= 2 dimensions are simultaneously elevated

* severity, impact and novelty are computed and stored alongside the scores.
"""
from __future__ import annotations

from app.controlplane.baselines import BaselineProvider, trace_metrics
from app.core.schemas import (
    AITrace,
    Dimension,
    DimensionRisk,
    EvaluationResult,
    Impact,
    RiskSummary,
    Severity,
)

_SEVERITY_MULT = {
    Severity.NONE: 0.6,
    Severity.LOW: 0.8,
    Severity.MEDIUM: 1.0,
    Severity.HIGH: 1.15,
    Severity.CRITICAL: 1.3,
}
_IMPACT_MULT = {Impact.LOW: 0.9, Impact.MEDIUM: 1.0, Impact.HIGH: 1.15}
_SEVERITY_ORDER = [Severity.NONE, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]

ELEVATED = 0.5          # a dimension is "elevated" at/above this raw risk
CROSS_RISK_BUMP = 0.15


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _impact_for(profile: dict) -> Impact:
    explicit = (profile or {}).get("business_impact")
    if explicit in {"low", "medium", "high"}:
        return Impact(explicit)
    return {
        "low": Impact.LOW,
        "medium": Impact.MEDIUM,
        "high": Impact.HIGH,
        "critical": Impact.HIGH,
    }.get((profile or {}).get("risk_class", "medium"), Impact.MEDIUM)


def _dampen_unfounded_judge(trace: AITrace, findings: list[EvaluationResult]) -> None:
    """When there is NO authoritative source, NO retrieval context and NO
    validated case, an LLM judge has nothing to check against. It may stay in
    the record as supporting evidence, but it must not drive the performance
    dimension or flip the state to "asserted false" (§17 no-ground-truth).
    Mutates in place so the audit record shows the down-weighting explicitly.
    """
    if trace.ground_truth_available or trace.retrieved_context or trace.authoritative_facts:
        return
    for f in findings:
        if f.dimension == Dimension.PERFORMANCE and f.evaluator.startswith("llm_judge"):
            if f.score > 0.5 or f.confidence > 0.3:
                f.reasons = [*f.reasons, "Down-weighted: no ground truth or retrieval context to verify against."]
            f.score = min(f.score, 0.5)
            f.confidence = min(f.confidence, 0.3)
            if f.label.startswith("judge_"):
                f.label = "judge_uncertain_no_ground_truth"
            if f.severity in (Severity.HIGH, Severity.CRITICAL):
                f.severity = Severity.MEDIUM


_UNSUPPORTED_LABELS = {"weak_grounding", "unsupported", "judge_unsupported", "judge_uncertain"}


def _reconcile_conflicting_evidence(findings: list[EvaluationResult]) -> None:
    """If the retrieved evidence is itself self-contradictory, we cannot be
    *confident* the answer is unsupported — only that we are uncertain. Cap the
    grounding / judge "unsupported" findings so conflicting evidence resolves to
    MEDIUM risk / LOW confidence (uncertainty) rather than a high-confidence
    "this answer is wrong". Mutates in place (visible in the audit record).
    """
    conf = next((f for f in findings if f.label == "conflicting_evidence" and f.score > 0), None)
    if conf is None:
        return
    for f in findings:
        if f is conf or f.dimension != Dimension.PERFORMANCE or f.label not in _UNSUPPORTED_LABELS:
            continue
        if f.score > conf.score or f.confidence > 0.4:
            f.reasons = [*f.reasons, "Confidence reduced: retrieved evidence is self-contradictory."]
        f.score = min(f.score, conf.score)
        f.confidence = min(f.confidence, 0.4)
        if f.severity in (Severity.HIGH, Severity.CRITICAL):
            f.severity = Severity.MEDIUM


def _aggregate_dimension(dim: Dimension, findings: list[EvaluationResult]) -> DimensionRisk:
    rel = [f for f in findings if f.dimension == dim and f.available]
    if not rel:
        return DimensionRisk(dimension=dim, risk=0.0, confidence=0.5, adjusted_risk=0.0)

    # risk = the strongest single finding (interpretable). Confidence = the
    # confidence of that strongest finding, nudged up if others corroborate.
    top = max(rel, key=lambda f: f.score)
    corroboration = sum(1 for f in rel if f.score >= max(0.2, top.score - 0.15) and f is not top)
    confidence = _clamp(top.confidence + 0.05 * corroboration)
    severity = max((f.severity for f in rel), key=_SEVERITY_ORDER.index)

    return DimensionRisk(
        dimension=dim,
        risk=round(top.score, 4),
        confidence=round(confidence, 4),
        severity=severity,
        labels=[f.label for f in rel if f.label not in {"ok", "no_pii", "no_bias_signal", "no_known_pattern"}],
        evaluators=[f.evaluator for f in rel],
    )


def _novelty(trace: AITrace, baselines: BaselineProvider | None, findings: list[EvaluationResult]) -> tuple[float, float]:
    """Return (novelty 0..1, baseline_confidence 0..1)."""
    known_pattern = any(f.label == "known_failure_pattern" for f in findings)
    if baselines is None:
        return (0.2 if known_pattern else 0.5), 0.4

    bconf = baselines.confidence
    metrics = trace_metrics(trace)
    zmax = 0.0
    for metric, value in metrics.items():
        b = baselines.get(metric)
        if b.n == 0:
            continue
        zmax = max(zmax, abs(b.robust_z(value)))

    if bconf < 0.5:                       # cold start — we genuinely don't know
        return 0.5, bconf
    novelty = _clamp((zmax - 3.0) / 6.0)  # z<=3 -> 0, z=9 -> 1
    if known_pattern:                     # a previously-confirmed failure is NOT novel
        novelty = min(novelty, 0.3)
    return round(novelty, 4), round(bconf, 4)


def assess(
    trace: AITrace,
    findings: list[EvaluationResult],
    workflow_profile: dict | None = None,
    baselines: BaselineProvider | None = None,
) -> RiskSummary:
    profile = workflow_profile or {}
    _dampen_unfounded_judge(trace, findings)
    _reconcile_conflicting_evidence(findings)
    perf = _aggregate_dimension(Dimension.PERFORMANCE, findings)
    cost = _aggregate_dimension(Dimension.COST, findings)
    resp = _aggregate_dimension(Dimension.RESPONSIBILITY, findings)

    impact = _impact_for(profile)

    # --- risk inheritance / compounding risk across agent steps & turns (§22) ---
    # Read from BOTH representations the session layer writes: trace metadata and
    # the terminal step's inherited_risk.
    inherited = float(trace.metadata.get("inherited_risk", 0.0))
    step_inherited = max((s.inherited_risk for s in trace.steps), default=0.0)
    inherited = max(inherited, step_inherited)
    consequential = bool(trace.metadata.get("consequential_action"))
    INHERIT_THRESHOLD = 0.35
    if inherited >= INHERIT_THRESHOLD:
        own_perf = perf.risk
        if inherited > own_perf:
            # carries more risk from earlier than it generates itself — pass it
            # through undecayed (the session layer owns decay).
            perf.risk = round(min(1.0, inherited), 4)
        elif own_perf >= 0.35:
            # this turn ADDS its own risk on top of inherited risk -> compounds
            perf.risk = round(min(1.0, max(own_perf, inherited) + 0.10), 4)
        perf.confidence = round(min(perf.confidence, 0.55), 4)
        if "inherited_risk" not in perf.labels:
            perf.labels.append("inherited_risk")
        # A consequential downstream action turns inherited uncertainty into
        # a high-impact situation regardless of the base profile.
        if consequential:
            impact = Impact.HIGH

    impact_mult = _IMPACT_MULT[impact]
    novelty, baseline_conf = _novelty(trace, baselines, findings)

    dims = [perf, cost, resp]
    for d in dims:
        d.adjusted_risk = round(
            _clamp(d.risk * _SEVERITY_MULT[d.severity] * impact_mult * max(d.confidence, 0.05)),
            4,
        )

    driver = max(dims, key=lambda d: d.adjusted_risk)
    overall = driver.adjusted_risk
    overall_conf = driver.confidence

    elevated = [d for d in dims if d.risk >= ELEVATED]
    cross = len(elevated) >= 2
    note = (
        f"overall = max(adjusted) = {driver.dimension.value} @ {overall:.3f}"
        f" (raw {driver.risk:.2f} x sev {_SEVERITY_MULT[driver.severity]} x impact {impact_mult} x conf {driver.confidence:.2f})"
    )
    if cross:
        overall = _clamp(overall + CROSS_RISK_BUMP)
        note += f"; cross-risk escalation +{CROSS_RISK_BUMP} ({', '.join(d.dimension.value for d in elevated)})"

    return RiskSummary(
        trace_id=trace.trace_id,
        performance=perf,
        cost=cost,
        responsibility=resp,
        impact=impact,
        novelty=novelty,
        baseline_confidence=baseline_conf,
        ground_truth_available=trace.ground_truth_available,
        inherited_risk=round(inherited, 4),
        consequential_action=consequential,
        data_classification=trace.data_classification,
        overall_risk=round(overall, 4),
        overall_confidence=round(overall_conf, 4),
        cross_risk_escalated=cross,
        aggregation_note=note,
    )
