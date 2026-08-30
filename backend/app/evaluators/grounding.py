"""Performance / "confidently wrong" detection (§14).

Layered evidence strategy, cheapest first:

  Level 1  authoritative structured facts   (strongest)   -- Tier 1
  Level 2  retrieved-context grounding                     -- Tier 1 cheap, Tier 2 TF-IDF
  Level 3  validated historical failure patterns           -- see failure_patterns.py
  Level 4  user feedback                                   -- see learning.py
  Level 5  human validation                                -- see learning.py

Key rule: with NO ground truth available, we do NOT declare "hallucination".
We report MEDIUM risk with LOW confidence and let impact/profile decide.
"""
from __future__ import annotations

import re

from app.evaluators._text import (
    containment,
    numbers_with_units,
    sentences,
    to_days,
)
from app.evaluators.base import BaseEvaluator, EvalContext, clamp, severity_from_score
from app.core.schemas import Dimension, EvaluationResult, Evidence, Severity

_CONCEPT_STOP = {"days", "count", "amount", "usd", "policy", "window", "limit", "max", "min", "number", "value"}
_CONFIDENT_MARKERS = re.compile(
    r"\b(definitely|certainly|guaranteed|without a doubt|absolutely|"
    r"will be exactly|is exactly|the answer is|precisely)\b",
    re.IGNORECASE,
)


def _keywords_from_key(key: str) -> list[str]:
    parts = re.split(r"[_\s]+", key.lower())
    return [p for p in parts if p not in _CONCEPT_STOP and len(p) > 2]


def _normalize_fact(key: str, raw: object) -> dict:
    if isinstance(raw, dict):
        kw = [k.lower() for k in raw.get("keywords", [])] or _keywords_from_key(key)
        return {
            "value": raw.get("value"),
            "unit": (raw.get("unit") or "").lower(),
            "keywords": kw,
            "statement": raw.get("statement"),
        }
    unit = "days" if key.endswith("_days") else ""
    return {"value": raw, "unit": unit, "keywords": _keywords_from_key(key), "statement": None}


def _near(text: str, offset: int, keywords: list[str], radius: int = 70) -> bool:
    lo, hi = max(0, offset - radius), min(len(text), offset + radius)
    window = text[lo:hi].lower()
    return any(kw in window for kw in keywords)


def _check_authoritative(ctx: EvalContext) -> tuple[float, float, list[str], list[Evidence], str | None]:
    facts = ctx.trace.authoritative_facts or {}
    response = ctx.trace.response_text or ""
    if not facts or not response:
        return 0.0, 0.0, [], [], None

    reasons: list[str] = []
    evidence: list[Evidence] = []
    contradiction_score = 0.0
    support_seen = False
    safe_response: str | None = None

    nums = numbers_with_units(response)
    for key, raw in facts.items():
        fact = _normalize_fact(key, raw)
        fval, funit, kws = fact["value"], fact["unit"], fact["keywords"]
        if fval is None or not isinstance(fval, (int, float)):
            # string fact: cheap containment check
            if isinstance(fval, str) and fval:
                if containment(fval, response) < 0.34 and any(k in response.lower() for k in kws):
                    contradiction_score = max(contradiction_score, 0.55)
                    reasons.append(f"Response discusses '{', '.join(kws)}' but does not match trusted value '{fval}'.")
                    evidence.append(Evidence(kind="authoritative_source", supports_response=False,
                                             detail=f"Trusted {key} = {fval}", ref_id=key, confidence=0.7))
            continue

        fact_days = to_days(float(fval), funit) if funit else None
        matched_here = False
        for val, unit, off in nums:
            if not _near(response, off, kws):
                continue
            matched_here = True
            cand_days = to_days(val, unit) if unit else None
            same = False
            if fact_days is not None and cand_days is not None:
                same = abs(fact_days - cand_days) < 0.5
            else:
                same = abs(val - float(fval)) < 0.5
            if same:
                support_seen = True
                evidence.append(Evidence(kind="authoritative_source", supports_response=True,
                                         detail=f"Response matches trusted {key} = {fval} {funit}".strip(),
                                         ref_id=key, confidence=0.9))
            else:
                contradiction_score = max(contradiction_score, 0.85)
                reasons.append(
                    f"Response states {val:g} {unit or ''}".strip()
                    + f" for '{', '.join(kws)}'; trusted source says {fval:g} {funit}".strip() + "."
                )
                evidence.append(Evidence(kind="authoritative_source", supports_response=False,
                                         detail=f"Trusted {key} = {fval} {funit}; response says {val:g} {unit}".strip(),
                                         ref_id=key, confidence=0.92))
                if fact["statement"]:
                    safe_response = fact["statement"]
        if not matched_here and kws and any(k in response.lower() for k in kws):
            # concept discussed, no number given — weak signal only
            pass

    if contradiction_score > 0:
        return contradiction_score, 0.92, reasons, evidence, safe_response
    if support_seen:
        return 0.0, 0.9, ["Response is consistent with the authoritative source."], evidence, None
    return 0.0, 0.0, [], [], None


def _check_grounding(ctx: EvalContext) -> tuple[float, float, list[str], list[Evidence]]:
    tr = ctx.trace
    response = tr.response_text or ""
    context_chunks = tr.retrieved_context or []

    if tr.evidence_expected and not context_chunks:
        return (
            0.5, 0.55,
            ["Workflow expects cited evidence, but no retrieval context was attached."],
            [Evidence(kind="retrieved_context", supports_response=False,
                      detail="Evidence expected; none present", confidence=0.55)],
        )

    if not context_chunks:
        return 0.0, 0.0, [], []

    joined = "\n".join(context_chunks)
    resp_sents = sentences(response) or [response]
    worst = 1.0
    for s in resp_sents:
        if len(s) < 12:
            continue
        worst = min(worst, containment(s, joined))
    # Tier 1 is deliberately forgiving — paraphrase legitimately lowers overlap.
    # Only a badly unsupported response should trip here; borderline cases are
    # left for the router to send to the Tier 2 TF-IDF check if it judges it
    # worthwhile (this keeps normal-traffic false positives low, §48).
    if worst >= 0.34:
        return (0.05, 0.68,
                [f"Response is supported by retrieved context (min token coverage {worst:.0%})."],
                [Evidence(kind="retrieved_context", supports_response=True,
                          detail=f"claim-to-context coverage {worst:.0%}", confidence=0.68)])
    score = clamp(0.22 + (0.34 - worst) * 1.2)
    return (score, 0.5,
            [f"Part of the response has low overlap with retrieved context (min coverage {worst:.0%})."],
            [Evidence(kind="retrieved_context", supports_response=False,
                      detail=f"low claim-to-context coverage {worst:.0%}", confidence=0.5)])


class GroundingEvaluator(BaseEvaluator):
    """Tier 1 cheap grounding: authoritative facts + token-overlap grounding."""

    name = "grounding_v1"
    dimension = Dimension.PERFORMANCE
    tier = 1
    cost_units = 1.0

    async def _run(self, ctx: EvalContext) -> EvaluationResult:
        tr = ctx.trace
        a_score, a_conf, a_reasons, a_ev, safe = _check_authoritative(ctx)
        g_score, g_conf, g_reasons, g_ev = _check_grounding(ctx)

        no_gt = (
            not tr.ground_truth_available
            and not tr.authoritative_facts
            and not tr.retrieved_context
        )

        if a_score > 0:  # authoritative contradiction dominates — strongest evidence
            score, confidence = a_score, a_conf
            label = "authoritative_contradiction"
            reasons = a_reasons
            evidence = a_ev + g_ev
        elif no_gt:
            confident = bool(_CONFIDENT_MARKERS.search(tr.response_text or ""))
            has_numbers = bool(numbers_with_units(tr.response_text or ""))
            score = 0.55 if (confident or has_numbers) else 0.4
            confidence = 0.25            # explicitly LOW — we cannot verify
            label = "no_ground_truth"
            reasons = [
                "No authoritative source, retrieved context, or validated case is available for this question.",
                "ControlPlane reduced evidence confidence rather than asserting the answer is false.",
            ]
            if confident:
                reasons.append("Response is phrased with high certainty despite the absence of verifiable evidence.")
            evidence = [Evidence(kind="no_ground_truth", supports_response=False,
                                 detail="ground_truth_available = false; no grounding evidence", confidence=0.25)]
        else:
            score = max(g_score, a_score)
            confidence = max(g_conf, a_conf, 0.45)
            label = "grounded" if score < 0.15 else "weak_grounding"
            reasons = g_reasons or a_reasons or ["No contradiction found against available evidence."]
            evidence = g_ev + a_ev

        return EvaluationResult(
            dimension=Dimension.PERFORMANCE,
            score=round(clamp(score), 4),
            confidence=round(clamp(confidence), 4),
            severity=severity_from_score(score) if label != "no_ground_truth" else Severity.MEDIUM,
            label=label,
            reasons=reasons,
            evidence=evidence,
            evaluator=self.name,
            tier=1,
            proposed_safe_response=safe,
        )


class DeepGroundingEvaluator(BaseEvaluator):
    """Tier 2 — sentence-level TF-IDF cosine grounding against retrieved context.

    More expensive than the Tier 1 token-overlap check; only runs when the
    router decides verification is worth the latency/compute.
    """

    name = "grounding_tfidf_v1"
    dimension = Dimension.PERFORMANCE
    tier = 2
    cost_units = 4.0

    async def _run(self, ctx: EvalContext) -> EvaluationResult:
        tr = ctx.trace
        context_chunks = tr.retrieved_context or []
        # Re-run the strong authoritative check first (cheap, decisive).
        a_score, a_conf, a_reasons, a_ev, safe = _check_authoritative(ctx)
        if a_score > 0:
            return EvaluationResult(
                dimension=Dimension.PERFORMANCE, score=round(a_score, 4), confidence=round(a_conf, 4),
                severity=severity_from_score(a_score), label="authoritative_contradiction",
                reasons=a_reasons, evidence=a_ev, evaluator=self.name, tier=2,
                proposed_safe_response=safe,
            )

        if not context_chunks:
            return EvaluationResult(
                dimension=Dimension.PERFORMANCE, score=0.4, confidence=0.3,
                severity=Severity.MEDIUM, label="no_context_for_deep_check",
                reasons=["Deep grounding requested but no retrieval context is available to verify against."],
                evidence=[Evidence(kind="no_ground_truth", supports_response=False,
                                   detail="no context for TF-IDF grounding", confidence=0.3)],
                evaluator=self.name, tier=2,
            )

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except Exception:  # noqa: BLE001 - fall back to the cheap check
            g_score, g_conf, g_reasons, g_ev = _check_grounding(ctx)
            return EvaluationResult(
                dimension=Dimension.PERFORMANCE, score=round(g_score, 4), confidence=round(g_conf, 4),
                severity=severity_from_score(g_score), label="weak_grounding" if g_score else "grounded",
                reasons=["scikit-learn unavailable; used token-overlap grounding.", *g_reasons],
                evidence=g_ev, evaluator=self.name, tier=2,
            )

        resp_sents = [s for s in sentences(tr.response_text) if len(s) >= 12] or [tr.response_text]
        docs = context_chunks + resp_sents
        tfidf = TfidfVectorizer(stop_words="english").fit_transform(docs)
        ctx_mat = tfidf[: len(context_chunks)]
        resp_mat = tfidf[len(context_chunks) :]
        sims = cosine_similarity(resp_mat, ctx_mat)
        per_sentence_max = sims.max(axis=1) if sims.size else [0.0]
        worst = float(min(per_sentence_max))
        mean = float(sum(per_sentence_max) / len(per_sentence_max))

        unsupported = [resp_sents[i] for i, v in enumerate(per_sentence_max) if v < 0.12]
        if worst >= 0.25:
            score, label = 0.05, "grounded"
        else:
            score = clamp(0.35 + (0.25 - worst) * 1.5)
            label = "unsupported" if unsupported else "weak_grounding"
        return EvaluationResult(
            dimension=Dimension.PERFORMANCE,
            score=round(score, 4),
            confidence=0.72,
            severity=severity_from_score(score),
            label=label,
            reasons=[
                f"TF-IDF grounding: min sentence similarity {worst:.2f}, mean {mean:.2f}.",
                *([f"Least-supported sentence: \"{unsupported[0][:120]}\""] if unsupported else []),
            ],
            evidence=[Evidence(kind="retrieved_context", supports_response=(score < 0.15),
                               detail=f"tfidf min={worst:.2f} mean={mean:.2f}", confidence=0.72)],
            evaluator=self.name,
            tier=2,
        )
