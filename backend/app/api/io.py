"""Request/response payloads for the HTTP API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import AITrace


class IngestTraceRequest(BaseModel):
    """Accepts a full normalized trace. Unknown workflows fall back to `default`."""

    trace: AITrace


class EvaluateRequest(BaseModel):
    trace: AITrace
    persist: bool = True
    enable_llm_judge: bool = True


class FeedbackRequest(BaseModel):
    trace_id: str
    thumbs: str = Field(pattern="^(up|down)$")
    reason: str = ""
    comment: str = ""
    source: str = "end_user"


class ReviewRequest(BaseModel):
    verdict: str          # correct|incorrect|unsafe|privacy_issue|biased|cost_issue|false_positive|other
    comment: str = ""
    authoritative: bool = False


class PolicyUpdateRequest(BaseModel):
    body: dict[str, Any]
    note: str = ""


class BenchmarkRequest(BaseModel):
    count: int = 500
    profile: str = "mixed"
    seed: int | None = None
    label: str = ""
    deep_eval_sim_latency_ms: float = 0.0   # illustrative "realistic deep path" latency


class DecisionView(BaseModel):
    """Flattened decision for the dashboard tables."""

    decision_id: str
    trace_id: str
    created_at: float
    application: str
    workflow: str
    action: str
    tier: int
    severity: str
    overall_risk: float
    performance_risk: float
    cost_risk: float
    responsibility_risk: float
    evidence_confidence: float
    controlplane_overhead_ms: float
    synchronous: bool
    requires_human_review: bool
    policy_version: str
