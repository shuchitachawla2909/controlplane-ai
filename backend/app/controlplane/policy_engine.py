"""Governance / policy layer (§11, §30, §64) and the decision matrix.

Nothing about the decision is hard-coded across the codebase: thresholds,
human-review rules and data policy all come from versioned YAML
(`config/policies`, `config/workflows`). Every decision records the exact
policy version that produced it.

Two questions are answered here:

1. ``route(...)``  -> is deeper verification worth the latency/compute?
   (risk x confidence x impact x novelty x budget — interpretable)
2. ``decide(...)`` -> which proportional action to take (the §11 matrix plus
   a few explicit rules for privacy, cost runaway and no-ground-truth).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings
from app.core.schemas import (
    Action,
    Dimension,
    Impact,
    RiskSummary,
    RoutingDecision,
)

_IMPACT_WEIGHT = {Impact.LOW: 0.3, Impact.MEDIUM: 0.6, Impact.HIGH: 1.0}

_DEFAULT_THRESHOLDS = {
    "performance": {"verify": 0.40, "escalate": 0.70},
    "cost": {"warn_multiplier": 1.5, "stop_multiplier": 3.0, "budget_usd": 0.10},
    "responsibility": {"redact": 0.50, "block": 0.80},
}
_DEFAULT_ROUTING = {
    "fast_path_below": 0.30,          # raw overall risk below this -> never verify
    "verify_value_threshold": 0.45,   # verification-value score to trigger Tier 2
    "min_confidence_for_block": 0.70,
    "tight_latency_ms": 1200,
    "novelty_force_verify": 0.75,
}


@dataclass
class ResolvedPolicy:
    name: str
    version: str
    workflow: str
    body: dict[str, Any]
    profile: dict[str, Any]

    def thr(self, dim: str) -> dict[str, float]:
        merged = dict(_DEFAULT_THRESHOLDS.get(dim, {}))
        merged.update((self.body.get("thresholds", {}) or {}).get(dim, {}) or {})
        return merged

    def routing(self) -> dict[str, float]:
        merged = dict(_DEFAULT_ROUTING)
        merged.update(self.body.get("routing", {}) or {})
        return merged

    def human_review_required_for(self) -> set[str]:
        hr = self.body.get("human_review", {}) or {}
        return set(hr.get("required_for", []))

    @property
    def latency_budget_ms(self) -> float:
        return float(self.profile.get("latency_budget_ms", self.body.get("latency", {}).get("budget_ms", 3000)))

    @property
    def cost_budget_usd(self) -> float:
        return float(self.profile.get("cost_budget_usd", self.thr("cost").get("budget_usd", 0.10)))


@dataclass
class DecisionOutcome:
    action: Action
    reasons: list[str] = field(default_factory=list)
    modification_method: str | None = None       # redaction | trusted_source_reconstruction | safe_fallback
    proposed_safe_response: str | None = None
    requires_human_review: bool = False
    execution_stopped: bool = False


# ---------------------------------------------------------------------------
# Policy store (versioned YAML -> ResolvedPolicy)
# ---------------------------------------------------------------------------
class PolicyStore:
    def __init__(self, config_dir: Path | None = None):
        s = get_settings()
        self.config_dir = config_dir or s.config_path
        self._policies: dict[str, dict[str, Any]] = {}
        self._workflows: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._policies.clear()
        self._workflows.clear()
        wf_dir = self.config_dir / "workflows"
        pol_dir = self.config_dir / "policies"
        for f in sorted(wf_dir.glob("*.y*ml")) if wf_dir.exists() else []:
            data = yaml.safe_load(f.read_text()) or {}
            key = data.get("workflow") or f.stem
            self._workflows[key] = data
        for f in sorted(pol_dir.glob("*.y*ml")) if pol_dir.exists() else []:
            data = yaml.safe_load(f.read_text()) or {}
            pol = data.get("policy", data)
            key = pol.get("workflow") or pol.get("name") or f.stem
            self._policies[key] = pol

    def register(self, workflow: str, policy_body: dict[str, Any], profile: dict[str, Any] | None = None) -> None:
        self._policies[workflow] = policy_body
        if profile is not None:
            self._workflows[workflow] = profile

    def workflows(self) -> dict[str, dict[str, Any]]:
        return dict(self._workflows)

    def policies(self) -> dict[str, dict[str, Any]]:
        return dict(self._policies)

    def resolve(self, workflow: str) -> ResolvedPolicy:
        pol = self._policies.get(workflow) or self._policies.get("default") or {}
        profile = self._workflows.get(workflow) or self._workflows.get("default") or {}
        name = pol.get("name", f"{workflow}_policy")
        version = str(pol.get("version", "0.0"))
        # merge profile-level knobs the policy also cares about
        body = dict(pol)
        return ResolvedPolicy(name=name, version=version, workflow=workflow, body=body, profile=dict(profile))


@lru_cache
def get_policy_store() -> PolicyStore:
    return PolicyStore()


# ---------------------------------------------------------------------------
# Routing — is deeper verification worth it?
# ---------------------------------------------------------------------------
def route(risk: RiskSummary, policy: ResolvedPolicy) -> RoutingDecision:
    r = policy.routing()
    raw = max(risk.performance.risk, risk.cost.risk, risk.responsibility.risk)
    reasons: list[str] = []

    # Clear-cut, high-confidence responsibility or cost -> act now, no Tier 2.
    resp_block = policy.thr("responsibility")["block"]
    if risk.responsibility.risk >= resp_block and risk.responsibility.confidence >= r["min_confidence_for_block"]:
        return RoutingDecision(verify=False, escalate=True, verification_value=1.0,
                               reasons=["High-confidence responsibility violation — act immediately, no Tier 2 needed."])
    if risk.cost.risk >= 0.75 and risk.cost.confidence >= 0.8:
        return RoutingDecision(verify=False, escalate=True, verification_value=1.0,
                               reasons=["Deterministic cost runaway — act immediately."])

    # Clearly low risk -> fast path.
    if raw < r["fast_path_below"]:
        return RoutingDecision(verify=False, escalate=False, verification_value=round(raw, 3),
                               reasons=[f"Raw risk {raw:.2f} below fast-path threshold {r['fast_path_below']:.2f}."])

    impact_w = _IMPACT_WEIGHT[risk.impact]
    value = (
        0.40 * raw
        + 0.30 * raw * (1.0 - risk.overall_confidence)   # verifying helps most when risky AND unsure
        + 0.20 * impact_w
        + 0.10 * risk.novelty
    )
    reasons.append(
        f"verification_value={value:.2f} "
        f"(risk {raw:.2f}, 1-confidence {1 - risk.overall_confidence:.2f}, impact {impact_w:.1f}, novelty {risk.novelty:.2f})"
    )

    tight = policy.latency_budget_ms <= r["tight_latency_ms"]
    async_ok = False
    if tight and raw < 0.6 and risk.impact != Impact.HIGH and risk.responsibility.risk < 0.5:
        value -= 0.15
        async_ok = True
        reasons.append(f"Latency budget is tight ({policy.latency_budget_ms:.0f}ms) — prefer async deep eval.")

    if risk.novelty >= r["novelty_force_verify"]:
        value = max(value, r["verify_value_threshold"])
        reasons.append(f"Novelty {risk.novelty:.2f} forces verification regardless of budget.")

    verify = value >= r["verify_value_threshold"]
    escalate = raw >= policy.thr("performance")["escalate"] and risk.overall_confidence >= 0.6
    return RoutingDecision(
        verify=verify and not escalate,
        escalate=escalate,
        async_deep_eval=verify and async_ok and not escalate,
        verification_value=round(value, 3),
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Decision matrix (§11) + explicit rules
# ---------------------------------------------------------------------------
def _band(x: float) -> str:
    if x < 0.25:
        return "low"
    if x < 0.5:
        return "medium"
    if x < 0.75:
        return "high"
    return "critical"


def decide(
    risk: RiskSummary,
    findings: list,
    policy: ResolvedPolicy,
    *,
    tier2_done: bool = False,
    projected_cost: float = 0.0,
    expected_cost: float = 0.0,
    in_flight: bool = False,
) -> DecisionOutcome:
    perf, cost, resp = risk.performance, risk.cost, risk.responsibility
    r = policy.routing()
    rt = policy.thr("responsibility")
    ct = policy.thr("cost")
    hr_rules = policy.human_review_required_for()
    reasons: list[str] = []

    def finding(pred):
        return next((f for f in findings if pred(f)), None)

    # proportional PII: block vs redact is data-class driven (configurable)
    data_policy = policy.body.get("data_policy", {}) or {}
    pii_action_map = data_policy.get("pii_action", {}) or {}

    def _pii_action_for(cls: str | None) -> str:
        return pii_action_map.get(cls or "unclassified", pii_action_map.get("default", "redact"))

    _HARD_RESP = {"secret_disclosure", "confidential_marking_leak", "weapon_synthesis",
                  "malware", "self_harm_encouragement", "violence_incitement", "bias_signal"}

    # ---- 1. Responsibility hard rules (privacy / safety / bias) -----------
    if resp.risk >= rt["block"] and resp.confidence >= r["min_confidence_for_block"]:
        pii_like = finding(lambda f: f.dimension == Dimension.RESPONSIBILITY
                           and f.label == "pii_leak" and f.proposed_safe_response)
        hard = any(lbl in _HARD_RESP for lbl in resp.labels)
        # PII-only exposure: redact when the data class allows it, else block.
        if pii_like and not hard and _pii_action_for(risk.data_classification) == "redact":
            return DecisionOutcome(
                action=Action.MODIFY,
                reasons=[
                    f"Sensitive-data exposure ({', '.join(l for l in resp.labels if l != 'ok')}); "
                    f"deterministic redaction applied (data class "
                    f"'{risk.data_classification or 'unclassified'}' -> redact).",
                ],
                modification_method="redaction",
                proposed_safe_response=pii_like.proposed_safe_response,
            )
        return DecisionOutcome(
            action=Action.BLOCK,
            reasons=[
                f"High-confidence responsibility violation ({', '.join(l for l in resp.labels if l != 'ok') or resp.severity.value})"
                + (f"; data class '{risk.data_classification}' -> block" if pii_like else "")
                + "; response withheld.",
            ],
        )
    if rt["redact"] <= resp.risk < rt["block"] and resp.confidence >= 0.5:
        pii_like = finding(lambda f: f.dimension == Dimension.RESPONSIBILITY and f.proposed_safe_response)
        if pii_like:
            return DecisionOutcome(
                action=Action.MODIFY,
                reasons=[f"Sensitive-data risk {resp.risk:.2f}; redacted before disclosure."],
                modification_method="redaction",
                proposed_safe_response=pii_like.proposed_safe_response,
            )

    # ---- 2. Cost runaway ------------------------------------------------
    budget = policy.cost_budget_usd
    runaway = (
        "cost_runaway" in cost.labels
        or (expected_cost and projected_cost >= ct["stop_multiplier"] * expected_cost)
        or (budget and projected_cost > budget and cost.confidence >= 0.75)
    )
    if runaway and cost.confidence >= 0.6:
        return DecisionOutcome(
            action=Action.STOP_EXECUTION if in_flight else Action.BLOCK,
            reasons=[
                f"Projected cost ${projected_cost:.3f} vs budget ${budget:.2f}"
                + (f" ({projected_cost / budget:.1f}x)" if budget else "")
                + ("; execution stopped." if in_flight else "; completed trace flagged, response blocked."),
            ],
            execution_stopped=in_flight,
        )

    # ---- 3. No ground truth + consequential workflow -------------------
    unresolved_uncertainty = (
        not risk.ground_truth_available
        and perf.risk >= policy.thr("performance")["verify"]
        and perf.confidence < 0.5
    )
    if unresolved_uncertainty and risk.impact == Impact.HIGH:
        wants_human = bool(hr_rules & {"unresolved_uncertainty_high_impact", "high_impact_decision"}) or policy.profile.get(
            "human_review_required_for_high_risk"
        )
        return DecisionOutcome(
            action=Action.HUMAN_REVIEW if wants_human else Action.SAFE_FALLBACK,
            reasons=[
                "No reliable ground truth was available; ControlPlane reduced confidence rather than asserting the answer is false.",
                f"High-impact workflow ({policy.workflow}) with unresolved uncertainty (perf risk {perf.risk:.2f}, confidence {perf.confidence:.2f}).",
            ],
            modification_method=None if wants_human else "safe_fallback",
            requires_human_review=wants_human,
        )

    # ---- 3b. Consequential agent action with unresolved risk (§22) -----
    if risk.consequential_action and (risk.inherited_risk >= 0.4 or perf.risk >= policy.thr("performance")["verify"]) \
            and risk.overall_confidence < 0.75:
        wants_human = bool(hr_rules & {"consequential_agent_action", "high_impact_decision"})
        return DecisionOutcome(
            action=Action.HUMAN_REVIEW if wants_human else Action.SAFE_FALLBACK,
            reasons=[
                "The agent is about to take a consequential / irreversible action while carrying unresolved risk "
                f"(inherited {risk.inherited_risk:.2f}, evidence confidence {risk.overall_confidence:.2f}).",
                "Compounding risk from earlier steps escalated this to human review.",
            ],
            modification_method=None if wants_human else "safe_fallback",
            requires_human_review=wants_human,
        )

    # ---- 4. Authoritative contradiction -------------------------------
    contra = finding(lambda f: f.label == "authoritative_contradiction")
    if contra and perf.confidence >= 0.7:
        if contra.proposed_safe_response:
            return DecisionOutcome(
                action=Action.MODIFY,
                reasons=[
                    "Response contradicts an authoritative source; replaced the unsupported claim with the verified statement.",
                    *contra.reasons[:1],
                ],
                modification_method="trusted_source_reconstruction",
                proposed_safe_response=contra.proposed_safe_response,
            )
        if risk.impact == Impact.HIGH:
            return DecisionOutcome(action=Action.HUMAN_REVIEW,
                                   reasons=["High-confidence contradiction in a high-impact workflow."],
                                   requires_human_review=True)
        if not tier2_done:
            return DecisionOutcome(action=Action.VERIFY, reasons=["Authoritative contradiction — verifying before disclosure."])
        return DecisionOutcome(action=Action.SAFE_FALLBACK, reasons=["Contradiction unresolved after verification."],
                               modification_method="safe_fallback")

    # ---- 4b. Unresolved uncertainty: conflicting evidence OR inherited risk --
    # Low-confidence high-risk is deflated in `overall_risk`, so the §11 matrix
    # under-reacts. Handle it explicitly: allow-with-monitoring (so the risk is
    # tracked and, in a session, propagates to a later consequential step) or
    # verify before disclosure. A turn with its OWN hard violation, or a
    # consequential action, is NOT handled here (rules 1-3b already covered it).
    unresolved = ("conflicting_evidence" in perf.labels) or ("inherited_risk" in perf.labels)
    own_hard_violation = (
        resp.risk >= rt["redact"]
        or "cost_runaway" in cost.labels
        or finding(lambda f: f.label == "authoritative_contradiction") is not None
    )
    if unresolved and not own_hard_violation and not risk.consequential_action \
            and perf.risk >= policy.thr("performance")["verify"] and perf.confidence <= 0.6:
        reasons = [
            "Unresolved risk (conflicting retrieved evidence and/or risk inherited from an earlier step)."
        ]
        if "inherited_risk" in perf.labels:
            reasons.append(f"Inherited risk {risk.inherited_risk:.2f} carried from an earlier turn.")
        reasons.append(
            "Allowing with monitoring so the unresolved risk is tracked." if tier2_done
            else "Verifying against the conflicting sources before disclosure."
        )
        return DecisionOutcome(action=Action.MONITOR if tier2_done else Action.VERIFY, reasons=reasons)

    # ---- 5. §11 matrix on overall adjusted risk x confidence ----------
    band = _band(risk.overall_risk)
    conf_high = risk.overall_confidence >= 0.6
    reasons.append(f"Matrix: overall risk {risk.overall_risk:.2f} ({band}), evidence confidence {risk.overall_confidence:.2f}.")

    if band == "low":
        outcome = DecisionOutcome(action=Action.ALLOW, reasons=reasons)
    elif band == "medium" and not conf_high:
        outcome = DecisionOutcome(action=Action.MONITOR, reasons=[*reasons, "Medium risk, low confidence -> allow + monitor (async deep eval)."])
    elif band == "medium" and conf_high:
        outcome = (
            DecisionOutcome(action=Action.VERIFY, reasons=[*reasons, "Medium risk, high confidence -> verify."])
            if not tier2_done
            else DecisionOutcome(action=Action.MONITOR, reasons=[*reasons, "Residual medium risk after verification -> monitor."])
        )
    elif band == "high" and not conf_high:
        if risk.impact == Impact.HIGH:
            outcome = DecisionOutcome(action=Action.SAFE_FALLBACK, reasons=[*reasons, "High risk, low confidence, high impact -> safe fallback."],
                                      modification_method="safe_fallback")
        elif not tier2_done:
            outcome = DecisionOutcome(action=Action.VERIFY, reasons=[*reasons, "High risk, low confidence -> verify."])
        else:
            outcome = DecisionOutcome(action=Action.SAFE_FALLBACK, reasons=[*reasons, "High risk unresolved after verification -> safe fallback."],
                                      modification_method="safe_fallback")
    elif band == "high" and conf_high:
        outcome = (
            DecisionOutcome(action=Action.HUMAN_REVIEW, reasons=[*reasons, "High risk + high confidence + high impact -> human review."], requires_human_review=True)
            if risk.impact == Impact.HIGH
            else DecisionOutcome(action=Action.BLOCK, reasons=[*reasons, "High risk + high confidence -> block."])
        )
    else:  # critical
        outcome = DecisionOutcome(
            action=Action.HUMAN_REVIEW if risk.impact == Impact.HIGH else Action.BLOCK,
            reasons=[*reasons, "Critical adjusted risk."],
            requires_human_review=risk.impact == Impact.HIGH,
        )

    # ---- 6. Catch-all: high-impact + unresolved uncertainty ----------
    if (
        risk.impact == Impact.HIGH
        and outcome.action in {Action.ALLOW, Action.MONITOR}
        and risk.overall_risk >= 0.40
        and risk.overall_confidence < 0.5
    ):
        return DecisionOutcome(
            action=Action.HUMAN_REVIEW,
            reasons=[*outcome.reasons, "High-impact workflow with unresolved uncertainty -> human review (override)."],
            requires_human_review=True,
        )
    return outcome
