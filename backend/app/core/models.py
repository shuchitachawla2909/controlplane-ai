"""Database tables.

Rich nested structures (execution steps, evidence lists, evaluator findings)
are stored as JSON columns — this is a prototype, not an OLAP warehouse, and
it keeps the schema readable. Sensitive raw payloads are NOT stored here by
default; see ``controlplane/observer.py`` for redaction-before-persist.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _now() -> float:
    return time.time()


class TraceRow(SQLModel, table=True):
    __tablename__ = "traces"

    trace_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    request_id: str = ""
    application: str = Field(index=True)
    workflow: str = Field(index=True)
    model: str = ""
    provider: str = ""
    created_at: float = Field(default_factory=_now, index=True)
    turn_index: int = 0
    in_flight: bool = False

    request_preview: str = ""       # truncated + redacted
    response_preview: str = ""      # truncated + redacted

    latency_ms: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    retrieval_events: int = 0
    retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    ground_truth_available: bool = True

    steps: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    trace_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class DecisionRow(SQLModel, table=True):
    __tablename__ = "decisions"

    decision_id: str = Field(primary_key=True)
    trace_id: str = Field(index=True)
    session_id: str = Field(default="", index=True)
    application: str = Field(default="", index=True)
    workflow: str = Field(default="", index=True)
    created_at: float = Field(default_factory=_now, index=True)

    policy_name: str = ""
    policy_version: str = ""

    performance_risk: float = 0.0
    cost_risk: float = 0.0
    responsibility_risk: float = 0.0
    performance_confidence: float = 0.0
    cost_confidence: float = 0.0
    responsibility_confidence: float = 0.0

    overall_risk: float = Field(default=0.0, index=True)
    evidence_confidence: float = 0.0
    severity: str = Field(default="none", index=True)
    impact: str = "low"
    novelty: float = 0.0

    action: str = Field(default="ALLOW", index=True)
    tier: int = Field(default=1, index=True)
    tiers_run: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    evaluators_run: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    verification_value: float = 0.0

    controlplane_overhead_ms: float = 0.0
    sequential_check_ms: float = 0.0
    parallel_check_ms: float = 0.0
    synchronous: bool = True

    projected_cost_usd: float = 0.0
    cost_budget_usd: float = 0.0
    prevented_spend_usd: float = 0.0
    execution_stopped: bool = False

    response_modified: bool = False
    modification_method: str | None = None
    requires_human_review: bool = Field(default=False, index=True)

    record: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class EvidenceRow(SQLModel, table=True):
    """Evidence store — feeds the learning loop. Confidence-tiered (§15)."""

    __tablename__ = "evidence"

    evidence_id: str = Field(primary_key=True)
    trace_id: str = Field(index=True)
    session_id: str = Field(default="", index=True)
    workflow: str = Field(default="", index=True)
    created_at: float = Field(default_factory=_now, index=True)

    kind: str = ""                  # user_feedback | human_validation | authoritative | machine_evidence
    trust_level: str = Field(default="raw_feedback", index=True)
    dimension: str = ""             # performance | cost | responsibility | ""
    verdict: str = ""              # correct | incorrect | unsafe | privacy_issue | biased | cost_issue | false_positive
    detail: str = ""
    pattern_signature: str = Field(default="", index=True)
    comment: str = ""
    source: str = "end_user"       # end_user | reviewer | system | authoritative
    duplicate_of: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class ReviewCaseRow(SQLModel, table=True):
    __tablename__ = "review_cases"

    case_id: str = Field(primary_key=True)
    trace_id: str = Field(index=True)
    decision_id: str = ""
    workflow: str = Field(default="", index=True)
    created_at: float = Field(default_factory=_now, index=True)
    status: str = Field(default="pending", index=True)  # pending | validated | dismissed
    reason: str = ""               # why it entered the queue
    suggested_labels: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    validated_at: float | None = None
    validator_verdict: str | None = None
    validator_comment: str = ""
    became_evidence_id: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class FailurePatternRow(SQLModel, table=True):
    """A known, validated failure pattern. Promoted only from trusted evidence."""

    __tablename__ = "failure_patterns"

    pattern_id: str = Field(primary_key=True)
    signature: str = Field(index=True)
    workflow: str = Field(default="", index=True)
    dimension: str = "performance"
    description: str = ""
    status: str = Field(default="candidate", index=True)  # candidate | trusted | retired
    evidence_count: int = 0
    trusted_evidence_count: int = 0
    risk_boost: float = 0.25
    created_at: float = Field(default_factory=_now)
    updated_at: float = Field(default_factory=_now)
    examples: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class BaselineRow(SQLModel, table=True):
    """Robust operational baseline per (workflow, metric)."""

    __tablename__ = "baselines"

    key: str = Field(primary_key=True)          # f"{workflow}:{metric}"
    workflow: str = Field(index=True)
    metric: str = ""
    n: int = 0
    median: float = 0.0
    p95: float = 0.0
    mad: float = 0.0
    mean: float = 0.0
    updated_at: float = Field(default_factory=_now)
    window: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    quarantined: list[float] = Field(default_factory=list, sa_column=Column(JSON))


class PolicyRow(SQLModel, table=True):
    """Versioned policy snapshot. A trace preserves the version it ran under."""

    __tablename__ = "policies"

    id: str = Field(primary_key=True)           # f"{name}:{version}"
    name: str = Field(index=True)
    version: str = ""
    workflow: str = Field(default="", index=True)
    active: bool = Field(default=True, index=True)
    created_at: float = Field(default_factory=_now)
    source: str = "file"                        # file | edited
    body: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class GoldenCaseRow(SQLModel, table=True):
    """Validated / golden examples that anchor the QUALITY baseline (§13)."""

    __tablename__ = "golden_cases"

    id: str = Field(primary_key=True)
    workflow: str = Field(default="", index=True)
    pattern_signature: str = Field(default="", index=True)
    question: str = ""
    trusted_answer: str = ""
    dimension: str = "performance"
    trust_level: str = "human_validated"
    created_at: float = Field(default_factory=_now)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class BenchmarkRunRow(SQLModel, table=True):
    __tablename__ = "benchmark_runs"

    run_id: str = Field(primary_key=True)
    created_at: float = Field(default_factory=_now, index=True)
    label: str = ""
    count: int = 0
    arms: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    north_star: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
