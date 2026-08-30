"""Normalized domain model for ControlPlane.ai.

This is the vendor-neutral contract every part of the system speaks. It is
deliberately compatible with the OpenTelemetry GenAI semantic conventions
(see ``adapters/otel.py`` for the field-by-field mapping) but does **not**
require an OpenTelemetry collector to be running.

Nothing here is coupled to a model provider, a framework, or a UI.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class StepType(str, Enum):
    LLM_CALL = "llm_call"
    RETRIEVAL = "retrieval"
    TOOL_CALL = "tool_call"
    FINAL_RESPONSE = "final_response"


class Dimension(str, Enum):
    PERFORMANCE = "performance"
    COST = "cost"
    RESPONSIBILITY = "responsibility"


class Severity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Action(str, Enum):
    ALLOW = "ALLOW"
    MONITOR = "MONITOR"
    MODIFY = "MODIFY"
    VERIFY = "VERIFY"
    BLOCK = "BLOCK"
    STOP_EXECUTION = "STOP_EXECUTION"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    SAFE_FALLBACK = "SAFE_FALLBACK"


class Confidence(str, Enum):
    """Trust level of a piece of evidence feeding the learning loop."""

    RAW_FEEDBACK = "raw_feedback"
    MACHINE_EVIDENCE = "machine_evidence"
    HUMAN_VALIDATED = "human_validated"
    AUTHORITATIVE = "authoritative"


def _uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Tier 0 — normalized execution trace
# ---------------------------------------------------------------------------
class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class TraceStep(BaseModel):
    """One node in the execution tree/DAG of an AI interaction.

    A simple prompt->response trace has a single FINAL_RESPONSE step. An agent
    trace has many LLM_CALL / RETRIEVAL / TOOL_CALL steps plus a terminal
    FINAL_RESPONSE. ``parent_id`` makes the structure a tree.
    """

    step_id: str = Field(default_factory=lambda: _uuid("step"))
    parent_id: str | None = None
    index: int = 0
    type: StepType

    name: str | None = None            # human label, e.g. "search_orders"
    model: str | None = None           # gen_ai.request.model
    provider: str | None = None        # gen_ai.system
    tool_name: str | None = None       # gen_ai.tool.name
    tool_type: str | None = None       # gen_ai.tool.type  (function | retrieval | ...)

    started_at: float = Field(default_factory=_now)
    duration_ms: float = 0.0
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    retries: int = 0

    # Retrieval steps attach the chunks they returned; grounding evaluators use this.
    retrieved_context: list[str] = Field(default_factory=list)

    input_meta: dict[str, Any] = Field(default_factory=dict)
    output_meta: dict[str, Any] = Field(default_factory=dict)

    # Populated by the in-flight agent hook / risk propagation.
    cumulative_cost_usd: float = 0.0
    risk_signals: list[str] = Field(default_factory=list)
    inherited_risk: float = 0.0


class AITrace(BaseModel):
    """A complete (or in-flight) AI interaction as ControlPlane sees it."""

    trace_id: str = Field(default_factory=lambda: _uuid("trace"))
    request_id: str = Field(default_factory=lambda: _uuid("req"))
    session_id: str = Field(default_factory=lambda: _uuid("sess"))

    application: str                    # e.g. "Customer Support Assistant"
    workflow: str                       # profile key, e.g. "customer_support"
    profile: str | None = None          # defaults to `workflow` if omitted

    model: str = "mock-model"
    provider: str = "mock"
    created_at: float = Field(default_factory=_now)

    request_text: str = ""
    response_text: str = ""

    steps: list[TraceStep] = Field(default_factory=list)

    # --- Evidence context supplied by the calling application -------------
    # RAG chunks used to build the answer (grounding evidence level 2).
    retrieved_context: list[str] = Field(default_factory=list)
    # Trusted structured facts (grounding evidence level 1 — strongest).
    # e.g. {"return_window_days": 30, "support_hours": "9am-6pm Mon-Fri"}
    authoritative_facts: dict[str, Any] = Field(default_factory=dict)
    # Does a reliable real-time ground truth exist for this question at all?
    ground_truth_available: bool = True
    # Is the workflow expected to cite evidence? (RAG assistants: yes)
    evidence_expected: bool = False
    # Standardized responsibility metadata owned by the calling application.
    data_classification: str | None = None      # public|internal|confidential|restricted
    turn_index: int = 0                          # position in a multi-turn session

    metadata: dict[str, Any] = Field(default_factory=dict)

    # Marks a trace whose execution is still running (agent in-flight hook).
    in_flight: bool = False

    # ----- Derived Tier 0 observations (filled by the Observer) ----------
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    retrieval_events: int = 0
    retries: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0

    def new_step(self, **kwargs: Any) -> TraceStep:
        step = TraceStep(index=len(self.steps), **kwargs)
        self.steps.append(step)
        return step


# ---------------------------------------------------------------------------
# Evidence + evaluator output
# ---------------------------------------------------------------------------
EvidenceKind = Literal[
    "authoritative_source",
    "retrieved_context",
    "failure_pattern",
    "user_feedback",
    "human_validation",
    "detector",
    "baseline",
    "llm_judge",
    "no_ground_truth",
]


class Evidence(BaseModel):
    kind: EvidenceKind
    supports_response: bool               # True = supports the answer, False = contradicts / concern
    detail: str
    ref_id: str | None = None
    confidence: float = 0.5              # 0..1 — how much we trust THIS piece of evidence

    def marker(self) -> str:
        if self.kind == "no_ground_truth":
            return "?"
        return "check" if self.supports_response else "cross"


class EvaluationResult(BaseModel):
    """Common structure returned by every evaluator (Tier 1 and Tier 2).

    Keeps the risk engine decoupled from any specific detector. Never carries
    hidden chain-of-thought — only score, concise reasons, evidence, version.
    """

    dimension: Dimension
    score: float = 0.0                   # 0..1 estimated RISK in this dimension
    confidence: float = 0.5             # 0..1 confidence that this assessment is correct
    severity: Severity = Severity.NONE
    label: str = "ok"
    reasons: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evaluator: str = "unknown_v0"       # name + version
    tier: int = 1
    latency_ms: float = 0.0

    # Optional deterministic remediation an evaluator can propose (used by MODIFY).
    # Never an LLM rewrite — redaction or trusted-source reconstruction only.
    proposed_safe_response: str | None = None
    available: bool = True              # False => capability not installed (e.g. Presidio)


# ---------------------------------------------------------------------------
# Risk engine output
# ---------------------------------------------------------------------------
class DimensionRisk(BaseModel):
    dimension: Dimension
    risk: float = 0.0                    # raw aggregated risk 0..1
    confidence: float = 0.5             # aggregated evidence confidence 0..1
    adjusted_risk: float = 0.0          # risk x severity x impact x confidence
    severity: Severity = Severity.NONE
    labels: list[str] = Field(default_factory=list)
    evaluators: list[str] = Field(default_factory=list)


class RiskSummary(BaseModel):
    trace_id: str
    performance: DimensionRisk
    cost: DimensionRisk
    responsibility: DimensionRisk

    impact: Impact = Impact.LOW
    novelty: float = 0.0                # 0..1 — how anomalous / unseen this interaction is
    baseline_confidence: float = 1.0    # low on cold start
    ground_truth_available: bool = True
    inherited_risk: float = 0.0         # unresolved risk carried in from earlier steps/turns
    consequential_action: bool = False  # this step performs an irreversible / high-impact action
    data_classification: str | None = None   # public|internal|confidential|restricted (from the app)

    overall_risk: float = 0.0
    overall_confidence: float = 0.5
    cross_risk_escalated: bool = False
    aggregation_note: str = ""

    def by_dimension(self, d: Dimension) -> DimensionRisk:
        return {
            Dimension.PERFORMANCE: self.performance,
            Dimension.COST: self.cost,
            Dimension.RESPONSIBILITY: self.responsibility,
        }[d]


# ---------------------------------------------------------------------------
# Decision / audit record
# ---------------------------------------------------------------------------
class RoutingDecision(BaseModel):
    """Output of the Tier router — did this interaction earn deeper checking?"""

    verify: bool                        # run Tier 2?
    escalate: bool                      # straight to Tier 3 / human?
    async_deep_eval: bool = False       # deep eval, but off the response critical path
    verification_value: float = 0.0    # interpretable score behind the choice
    reasons: list[str] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    """The structured, auditable reason for every ControlPlane decision."""

    decision_id: str = Field(default_factory=lambda: _uuid("dec"))
    trace_id: str
    session_id: str = ""
    application: str = ""
    workflow: str = ""
    policy_name: str = ""
    policy_version: str = ""

    created_at: float = Field(default_factory=_now)

    # component scores — the UI ALWAYS shows these, never just `overall_risk`
    performance_risk: float = 0.0
    cost_risk: float = 0.0
    responsibility_risk: float = 0.0
    performance_confidence: float = 0.0
    cost_confidence: float = 0.0
    responsibility_confidence: float = 0.0

    overall_risk: float = 0.0
    evidence_confidence: float = 0.0
    severity: Severity = Severity.NONE
    impact: Impact = Impact.LOW
    novelty: float = 0.0
    ground_truth_available: bool = True

    tier: int = 1                                # highest tier reached
    tiers_run: list[int] = Field(default_factory=list)
    evaluators_run: list[str] = Field(default_factory=list)
    verification_value: float = 0.0

    action: Action = Action.ALLOW
    reasons: list[str] = Field(default_factory=list)

    # explainability (§58) — five plain-language answers
    what_happened: str = ""
    how_detected: str = ""
    how_confident: str = ""
    why_action: str = ""
    what_we_did: str = ""

    # response handling
    original_response: str = ""
    original_response_redacted: bool = False     # True when persisted with sensitive spans masked
    safe_response: str = ""
    response_modified: bool = False
    modification_method: str | None = None      # redaction | trusted_source_reconstruction | safe_fallback

    # cost control
    projected_cost_usd: float = 0.0
    cost_budget_usd: float = 0.0
    prevented_spend_usd: float = 0.0
    execution_stopped: bool = False

    # latency accounting
    controlplane_overhead_ms: float = 0.0
    sequential_check_ms: float = 0.0
    parallel_check_ms: float = 0.0
    synchronous: bool = True

    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[EvaluationResult] = Field(default_factory=list)

    requires_human_review: bool = False
    simulated: bool = True                       # prototype simulation — never a real financial claim
