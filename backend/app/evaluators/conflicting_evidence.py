"""Conflicting-evidence detection (Tier 1) — a first-class uncertainty signal.

When retrieved context contains mutually contradictory values for the same
concept, ControlPlane should represent *uncertainty*, not assert that the
answer is wrong. This produces MEDIUM performance risk with LOW confidence and
lets the router / policy decide (and, in a multi-turn session, this unresolved
risk propagates forward — see controlplane/sessions.py).

Deliberately conservative:
* needs >= 2 retrieved chunks (or an explicit ``conflicting_evidence`` marker
  on a step's ``risk_signals``);
* only compares numbers that are genuinely comparable (same unit, or both
  large unitless magnitudes) and differ by a clear margin;
* requires a shared, non-structural concept word near both numbers;
* returns zero risk on ordinary non-conflicting multi-chunk retrieval.
"""
from __future__ import annotations

from itertools import combinations

from app.evaluators._text import content_tokens, numbers_with_units, to_days
from app.evaluators.base import BaseEvaluator, EvalContext
from app.core.schemas import Dimension, EvaluationResult, Evidence, Severity

# words that carry no conceptual meaning for a value (version/page/clause numbers)
_META_TOKENS = {
    "doc", "docs", "document", "version", "revision", "rev", "page", "pages",
    "section", "clause", "item", "number", "ref", "reference", "row", "line",
    "note", "appendix", "exhibit", "figure", "table", "chapter", "part", "rule",
    "paragraph", "step", "v1", "v2", "v3", "v4", "id",
}
_MIN_RATIO = 1.2           # values must differ by at least this factor
_LARGE_UNITLESS = 100.0    # unitless numbers below this are treated as labels, not quantities
_RADIUS = 70


def _concept_near(text: str, offset: int) -> set[str]:
    lo, hi = max(0, offset - _RADIUS), min(len(text), offset + _RADIUS)
    return {t for t in content_tokens(text[lo:hi]) if len(t) > 3} - _META_TOKENS


def _comparable(vi: float, ui: str, vj: float, uj: str) -> tuple[float, float] | None:
    di, dj = (to_days(vi, ui) if ui else None), (to_days(vj, uj) if uj else None)
    if ui and uj:
        if di is not None and dj is not None:
            return di, dj
        return (vi, vj) if ui == uj else None
    if not ui and not uj:
        # unitless numbers below ~100 are usually labels (version, page, tier,
        # small ranges like "9-6"); comparing them produces false positives on
        # ranges and boilerplate, so we only compare large unitless magnitudes.
        return (vi, vj) if (vi >= _LARGE_UNITLESS and vj >= _LARGE_UNITLESS) else None
    return None  # one carries a unit, the other doesn't


class ConflictingEvidenceEvaluator(BaseEvaluator):
    name = "conflicting_evidence_v1"
    dimension = Dimension.PERFORMANCE
    tier = 1
    cost_units = 0.3

    async def _run(self, ctx: EvalContext) -> EvaluationResult:
        tr = ctx.trace
        chunks = [c for c in (tr.retrieved_context or []) if c and c.strip()]
        explicit = any("conflicting_evidence" in (s.risk_signals or []) for s in tr.steps)

        conflicts: list[str] = []
        if len(chunks) >= 2:
            for i, j in combinations(range(len(chunks)), 2):
                ni, nj = numbers_with_units(chunks[i]), numbers_with_units(chunks[j])
                for vi, ui, oi in ni:
                    for vj, uj, oj in nj:
                        pair = _comparable(vi, ui, vj, uj)
                        if not pair:
                            continue
                        a, b = pair
                        if a <= 0 or b <= 0 or max(a, b) / min(a, b) < _MIN_RATIO:
                            continue
                        shared = _concept_near(chunks[i], oi) & _concept_near(chunks[j], oj)
                        if not shared:
                            continue
                        term = sorted(shared)[0]
                        conflicts.append(
                            f"'{term}': {vi:g}{(' ' + ui) if ui else ''} vs {vj:g}{(' ' + uj) if uj else ''}"
                        )

        if not conflicts and not explicit:
            return EvaluationResult(
                dimension=Dimension.PERFORMANCE, score=0.0, confidence=0.6,
                severity=Severity.NONE, label="no_conflict",
                reasons=["Retrieved context is consistent (no conflicting values for the same concept)."]
                if len(chunks) >= 2 else ["Not enough retrieved context to assess consistency."],
                evaluator=self.name, tier=1,
            )

        detail = conflicts[0] if conflicts else "tracing layer flagged conflicting_evidence"
        reasons = [
            "Retrieved context contains conflicting information for the same concept; "
            "the answer cannot be confidently grounded.",
            f"Conflict: {detail}.",
            "ControlPlane represents this as uncertainty (low confidence), not as a proven-wrong answer.",
        ]
        return EvaluationResult(
            dimension=Dimension.PERFORMANCE,
            score=0.5 if explicit else 0.45,
            confidence=0.3,                       # explicitly LOW — evidence is unreliable, not the answer
            severity=Severity.MEDIUM,
            label="conflicting_evidence",
            reasons=reasons,
            evidence=[Evidence(kind="retrieved_context", supports_response=False,
                               detail=f"conflicting retrieved values ({detail})", confidence=0.4)],
            evaluator=self.name,
            tier=1,
        )
