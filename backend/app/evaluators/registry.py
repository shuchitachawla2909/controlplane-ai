"""Evaluator catalog. The router picks from here; nothing else imports the
concrete evaluator classes directly.
"""
from __future__ import annotations

from app.evaluators.base import Evaluator
from app.evaluators.bias import BiasEvaluator, CounterfactualBiasEvaluator
from app.evaluators.conflicting_evidence import ConflictingEvidenceEvaluator
from app.evaluators.cost import CostEvaluator
from app.evaluators.grounding import DeepGroundingEvaluator, GroundingEvaluator
from app.evaluators.failure_patterns import FailurePatternEvaluator
from app.evaluators.llm_judge import OptionalLLMJudgeEvaluator
from app.evaluators.pii import PIIEvaluator
from app.evaluators.responsibility import ResponsibilityEvaluator
from app.core.schemas import Dimension


def tier1_evaluators() -> list[Evaluator]:
    """Cheap, deterministic, independent — always run, dispatched together."""
    return [
        CostEvaluator(),
        GroundingEvaluator(),
        ConflictingEvidenceEvaluator(),
        FailurePatternEvaluator(),
        PIIEvaluator(),
        ResponsibilityEvaluator(),
        BiasEvaluator(),
    ]


def deep_evaluators_for(dimensions: set[Dimension], enable_llm_judge: bool = True) -> list[Evaluator]:
    """Tier 2 evaluators selected by which dimensions the router wants verified."""
    out: list[Evaluator] = []
    if Dimension.PERFORMANCE in dimensions:
        out.append(DeepGroundingEvaluator())
        if enable_llm_judge:
            out.append(OptionalLLMJudgeEvaluator())
    if Dimension.RESPONSIBILITY in dimensions:
        out.append(CounterfactualBiasEvaluator())
    # Cost is already deterministic at Tier 1 — no deeper check adds signal.
    return out


ALL_TIER2 = [DeepGroundingEvaluator, OptionalLLMJudgeEvaluator, CounterfactualBiasEvaluator]
