"""Decision matrix (§11) — allow / modify / verify / block / stop / human."""
from __future__ import annotations

from app.controlplane.policy_engine import PolicyStore, decide, route
from app.controlplane import risk_engine
from app.core.schemas import (
    AITrace,
    Action,
    Dimension,
    EvaluationResult,
    Severity,
)

STORE = PolicyStore()


def _risk(trace, findings, wf):
    p = STORE.resolve(wf)
    return risk_engine.assess(trace, findings, p.profile), p


def _t(wf="customer_support", **kw):
    return AITrace(application="x", workflow=wf, request_text="q", response_text="a", **kw)


def _f(dim, score, conf, sev=Severity.MEDIUM, label="x", safe=None):
    return EvaluationResult(dimension=dim, score=score, confidence=conf, severity=sev, label=label,
                            evaluator="t", proposed_safe_response=safe)


def test_low_risk_allows_on_fast_path():
    r, p = _risk(_t(), [_f(Dimension.PERFORMANCE, 0.05, 0.8, Severity.NONE, "ok")], "customer_support")
    assert route(r, p).verify is False
    assert decide(r, [], p).action == Action.ALLOW


def test_confidential_pii_blocks_but_internal_pii_redacts():
    """Proportional privacy action is data-class driven (P1-6)."""
    findings = [_f(Dimension.RESPONSIBILITY, 0.9, 0.95, Severity.CRITICAL, "pii_leak", safe="[REDACTED_EMAIL_ADDRESS]")]

    r_conf, p = _risk(_t("customer_support", data_classification="confidential"), findings, "customer_support")
    assert decide(r_conf, findings, p).action == Action.BLOCK

    r_int, p = _risk(_t("customer_support", data_classification="internal"), findings, "customer_support")
    out = decide(r_int, findings, p)
    assert out.action == Action.MODIFY and out.modification_method == "redaction"


def test_secret_disclosure_always_blocks_regardless_of_class():
    findings = [_f(Dimension.RESPONSIBILITY, 0.9, 0.95, Severity.CRITICAL, "secret_disclosure")]
    r, p = _risk(_t("customer_support", data_classification="internal"), findings, "customer_support")
    assert decide(r, findings, p).action == Action.BLOCK


def test_authoritative_contradiction_reconstructs_from_trusted_source():
    findings = [_f(Dimension.PERFORMANCE, 0.85, 0.92, Severity.HIGH, "authoritative_contradiction",
                   safe="Returns are accepted within 30 days of delivery.")]
    r, p = _risk(_t(), findings, "customer_support")
    out = decide(r, findings, p, tier2_done=True)
    assert out.action == Action.MODIFY
    assert out.modification_method == "trusted_source_reconstruction"


def test_cost_runaway_stops_when_in_flight():
    findings = [_f(Dimension.COST, 0.9, 0.9, Severity.CRITICAL, "cost_runaway")]
    r, p = _risk(_t("agent_operations", in_flight=True), findings, "agent_operations")
    out = decide(r, findings, p, projected_cost=0.31, expected_cost=0.03, in_flight=True)
    assert out.action == Action.STOP_EXECUTION and out.execution_stopped


def test_no_ground_truth_high_impact_requires_human_or_fallback():
    findings = [_f(Dimension.PERFORMANCE, 0.55, 0.25, Severity.MEDIUM, "no_ground_truth")]
    r, p = _risk(_t("decision_support", ground_truth_available=False), findings, "decision_support")
    out = decide(r, findings, p)
    assert out.action in {Action.HUMAN_REVIEW, Action.SAFE_FALLBACK}


def test_medium_risk_low_confidence_allows_with_monitor():
    findings = [_f(Dimension.PERFORMANCE, 0.4, 0.4, Severity.MEDIUM, "weak_grounding")]
    r, p = _risk(_t(), findings, "customer_support")
    out = decide(r, findings, p, tier2_done=True)
    assert out.action in {Action.MONITOR, Action.ALLOW, Action.SAFE_FALLBACK}


def test_policy_version_is_available_for_audit():
    p = STORE.resolve("customer_support")
    assert p.name == "customer_support_v1" and p.version == "1.0"
