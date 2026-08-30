"""Evaluator abstraction (§8, §60).

Every check — cheap Tier 1 or expensive Tier 2 — implements the same
interface and returns the same ``EvaluationResult`` structure. The risk engine
never knows which concrete evaluator produced a finding.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.schemas import (
    AITrace,
    Dimension,
    EvaluationResult,
    Evidence,
    Severity,
)


@dataclass
class EvalContext:
    """Everything an evaluator may need. Assembled once per trace by the router."""

    trace: AITrace
    policy: dict[str, Any]
    workflow_profile: dict[str, Any]
    tier: int = 1
    prior_evidence: list[Evidence] = field(default_factory=list)
    trusted_failure_patterns: list[dict[str, Any]] = field(default_factory=list)
    baseline_lookup: Any = None            # BaselineProvider (see controlplane/baselines.py)
    llm_provider: str = "mock"

    def thresholds(self, dimension: str) -> dict[str, float]:
        return (self.policy.get("thresholds", {}) or {}).get(dimension, {}) or {}


@runtime_checkable
class Evaluator(Protocol):
    name: str
    dimension: Dimension
    tier: int
    cost_units: float          # relative checker cost, for benchmark accounting

    async def evaluate(self, ctx: EvalContext) -> EvaluationResult: ...


class BaseEvaluator:
    """Convenience base: times the run and guarantees a well-formed result."""

    name: str = "base_v0"
    dimension: Dimension = Dimension.PERFORMANCE
    tier: int = 1
    cost_units: float = 1.0

    async def _run(self, ctx: EvalContext) -> EvaluationResult:  # pragma: no cover
        raise NotImplementedError

    async def evaluate(self, ctx: EvalContext) -> EvaluationResult:
        started = time.perf_counter()
        try:
            result = await self._run(ctx)
        except Exception as exc:  # an evaluator failure must not break the pipeline
            result = EvaluationResult(
                dimension=self.dimension,
                score=0.0,
                confidence=0.0,
                severity=Severity.NONE,
                label="evaluator_error",
                reasons=[f"{self.name} failed: {exc!s}"],
                evaluator=self.name,
                tier=self.tier,
                available=False,
            )
        result.evaluator = result.evaluator or self.name
        result.tier = self.tier
        result.latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return result


def severity_from_score(score: float) -> Severity:
    if score >= 0.85:
        return Severity.CRITICAL
    if score >= 0.6:
        return Severity.HIGH
    if score >= 0.35:
        return Severity.MEDIUM
    if score >= 0.15:
        return Severity.LOW
    return Severity.NONE


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ok_result(dimension: Dimension, evaluator: str, tier: int, note: str = "no issue detected") -> EvaluationResult:
    return EvaluationResult(
        dimension=dimension,
        score=0.0,
        confidence=0.7,
        severity=Severity.NONE,
        label="ok",
        reasons=[note],
        evaluator=evaluator,
        tier=tier,
    )
