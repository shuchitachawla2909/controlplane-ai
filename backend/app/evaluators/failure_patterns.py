"""Evidence level 3 — validated historical failure patterns (§14).

This evaluator is the visible link in the learning loop: when the review queue
promotes a *trusted* failure pattern (from human/authoritative validation), a
later interaction that matches the same signature gets extra performance risk
and is far more likely to be routed to deep verification than it was before.

Raw user feedback never reaches here — only promoted, trusted patterns do.
"""
from __future__ import annotations

from app.controlplane.signatures import signature_for
from app.evaluators.base import BaseEvaluator, EvalContext, clamp, severity_from_score
from app.core.schemas import Dimension, EvaluationResult, Evidence, Severity


class FailurePatternEvaluator(BaseEvaluator):
    name = "failure_pattern_v1"
    dimension = Dimension.PERFORMANCE
    tier = 1
    cost_units = 0.2

    async def _run(self, ctx: EvalContext) -> EvaluationResult:
        patterns = ctx.trusted_failure_patterns or []
        if not patterns:
            return EvaluationResult(
                dimension=Dimension.PERFORMANCE, score=0.0, confidence=0.5,
                severity=Severity.NONE, label="no_known_pattern",
                reasons=["No validated failure pattern matches this interaction."],
                evaluator=self.name, tier=1,
            )

        sig = signature_for(ctx.trace.workflow, ctx.trace.request_text or ctx.trace.response_text)
        match = next((p for p in patterns if p.get("signature") == sig), None)
        if not match:
            return EvaluationResult(
                dimension=Dimension.PERFORMANCE, score=0.0, confidence=0.5,
                severity=Severity.NONE, label="no_known_pattern",
                reasons=[f"Interaction signature '{sig}' does not match any trusted failure pattern."],
                evaluator=self.name, tier=1,
            )

        count = int(match.get("trusted_evidence_count", match.get("evidence_count", 1)))
        boost = float(match.get("risk_boost", 0.25))
        score = clamp(0.45 + boost + 0.03 * max(0, count - 1))
        confidence = clamp(0.62 + 0.05 * count, 0.62, 0.9)
        return EvaluationResult(
            dimension=Dimension.PERFORMANCE,
            score=round(score, 4),
            confidence=round(confidence, 4),
            severity=severity_from_score(score),
            label="known_failure_pattern",
            reasons=[
                f"Matches validated failure pattern '{match.get('signature')}' "
                f"({count} human/authoritative-confirmed case(s)).",
                match.get("description", ""),
                "Routing raised because this class of question has produced confirmed errors before.",
            ],
            evidence=[Evidence(kind="failure_pattern", supports_response=False,
                               detail=f"{match.get('signature')} x{count} validated",
                               ref_id=match.get("pattern_id"), confidence=confidence)],
            evaluator=self.name,
            tier=1,
        )
