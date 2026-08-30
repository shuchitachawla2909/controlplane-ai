"""Optional LLM-as-judge (§8, §59) — Tier 2 only, never on the fast path.

* Default provider is the deterministic mock judge (offline, reproducible).
* A real OpenAI-compatible judge is used only if configured.
* We store score + concise reason + evidence + evaluator version.
  We never request or store hidden chain-of-thought.
"""
from __future__ import annotations

from app.adapters.providers import get_model_adapter
from app.evaluators.base import BaseEvaluator, EvalContext, clamp, severity_from_score
from app.core.schemas import Dimension, EvaluationResult, Evidence, Severity


class OptionalLLMJudgeEvaluator(BaseEvaluator):
    name = "llm_judge_v1"
    dimension = Dimension.PERFORMANCE
    tier = 2
    cost_units = 10.0  # by far the most expensive check — reserved for Tier 2

    async def _run(self, ctx: EvalContext) -> EvaluationResult:
        tr = ctx.trace
        adapter = get_model_adapter(ctx.llm_provider)
        verdict = await adapter.judge(
            question=tr.request_text,
            answer=tr.response_text,
            context=tr.retrieved_context or None,
            criteria="Is the answer supported by the evidence and free of unsupported specifics?",
        )
        score = clamp(float(verdict.get("score", 0.5)))
        confidence = clamp(float(verdict.get("confidence", 0.5)))
        label = str(verdict.get("label", "uncertain"))
        # No ground truth => a judge cannot manufacture it; cap its confidence.
        if not tr.ground_truth_available and not tr.retrieved_context:
            confidence = min(confidence, 0.35)

        return EvaluationResult(
            dimension=Dimension.PERFORMANCE,
            score=round(score, 4),
            confidence=round(confidence, 4),
            severity=severity_from_score(score),
            label=f"judge_{label}",
            reasons=[f"LLM judge ({adapter.name}): {verdict.get('reason', 'n/a')}",
                     f"evaluator={verdict.get('evaluator_version', self.name)}"],
            evidence=[Evidence(kind="llm_judge", supports_response=(label == "supported"),
                               detail=str(verdict.get("reason", "")), confidence=confidence)],
            evaluator=self.name,
            tier=2,
        )
