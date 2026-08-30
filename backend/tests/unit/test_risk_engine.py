from __future__ import annotations

from app.controlplane import risk_engine
from app.core.schemas import (
    AITrace,
    Dimension,
    EvaluationResult,
    Severity,
)


def _trace(workflow="customer_support", **kw) -> AITrace:
    return AITrace(application="x", workflow=workflow, request_text="q", response_text="a", **kw)


def _f(dim, score, conf, sev=Severity.MEDIUM, label="x") -> EvaluationResult:
    return EvaluationResult(dimension=dim, score=score, confidence=conf, severity=sev, label=label, evaluator="t")


def test_low_risk_all_dimensions():
    r = risk_engine.assess(_trace(), [_f(Dimension.PERFORMANCE, 0.05, 0.8, Severity.NONE)], {"risk_class": "medium"})
    assert r.overall_risk < 0.15


def test_components_stay_separate_and_visible():
    findings = [
        _f(Dimension.PERFORMANCE, 0.1, 0.8, Severity.LOW),
        _f(Dimension.COST, 0.08, 0.9, Severity.NONE),
        _f(Dimension.RESPONSIBILITY, 0.95, 0.9, Severity.CRITICAL),
    ]
    r = risk_engine.assess(_trace(), findings, {"risk_class": "medium"})
    # not an average — responsibility keeps overall high
    assert r.responsibility.risk == 0.95
    assert r.performance.risk == 0.1 and r.cost.risk == 0.08
    assert r.overall_risk >= 0.7


def test_cross_risk_escalation():
    findings = [
        _f(Dimension.PERFORMANCE, 0.6, 0.7, Severity.HIGH),
        _f(Dimension.RESPONSIBILITY, 0.6, 0.7, Severity.HIGH),
    ]
    r = risk_engine.assess(_trace(), findings, {"risk_class": "medium"})
    assert r.cross_risk_escalated is True


def test_high_impact_profile_raises_adjusted_risk():
    findings = [_f(Dimension.PERFORMANCE, 0.5, 0.7, Severity.MEDIUM)]
    low = risk_engine.assess(_trace("customer_support"), findings, {"risk_class": "medium", "business_impact": "medium"})
    high = risk_engine.assess(_trace("decision_support"), findings, {"risk_class": "high", "business_impact": "high"})
    assert high.overall_risk > low.overall_risk
    assert high.impact.value == "high"


def test_no_ground_truth_flows_through():
    r = risk_engine.assess(
        _trace(ground_truth_available=False),
        [_f(Dimension.PERFORMANCE, 0.55, 0.25, Severity.MEDIUM, "no_ground_truth")],
        {"risk_class": "high", "business_impact": "high"},
    )
    assert r.ground_truth_available is False
    assert r.overall_confidence < 0.5


def test_inherited_risk_compounds():
    t = _trace("agent_operations", metadata={"inherited_risk": 0.7, "consequential_action": True})
    r = risk_engine.assess(t, [_f(Dimension.PERFORMANCE, 0.1, 0.8, Severity.LOW)], {"risk_class": "high"})
    assert r.performance.risk >= 0.6
    assert "inherited_risk" in r.performance.labels
    assert r.impact.value == "high"
