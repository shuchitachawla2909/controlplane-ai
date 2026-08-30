"""Cost anomaly detection (§B, §23).

The most deterministic dimension — NO LLM is used here. A runaway agent is
identified from execution telemetry alone: token / model-call / tool-call /
retry / latency deviation from the workflow baseline, plus current-vs-expected
cost and (for in-flight agents) cost trajectory.
"""
from __future__ import annotations

from app.controlplane.cost_model import project_final_cost
from app.evaluators.base import BaseEvaluator, EvalContext, clamp, severity_from_score
from app.core.schemas import Dimension, EvaluationResult, Evidence, Severity


def _mult(baseline_provider, metric: str, value: float) -> tuple[float, float, bool]:
    """Return (multiplier vs median, robust_z, cold_start)."""
    if baseline_provider is None:
        return 1.0, 0.0, True
    b = baseline_provider.get(metric)
    return b.multiplier(value), b.robust_z(value), b.is_cold_start


class CostEvaluator(BaseEvaluator):
    name = "cost_v1"
    dimension = Dimension.COST
    tier = 1
    cost_units = 0.2  # extremely cheap — pure arithmetic

    async def _run(self, ctx: EvalContext) -> EvaluationResult:
        tr = ctx.trace
        profile = ctx.workflow_profile or {}
        cost_thr = ctx.thresholds("cost")
        warn_mult = float(cost_thr.get("warn_multiplier", 1.5))
        stop_mult = float(cost_thr.get("stop_multiplier", 3.0))
        budget = float(profile.get("cost_budget_usd", cost_thr.get("budget_usd", 0.10)))
        max_tool_calls = profile.get("max_tool_calls")
        max_model_calls = profile.get("max_model_calls")

        bp = ctx.baseline_lookup
        current_cost = tr.estimated_cost_usd
        expected_cost = None
        if bp is not None:
            eb = bp.get("cost_usd")
            expected_cost = eb.median if eb.n else None

        projected_cost, trajectory = project_final_cost(tr, expected_cost)

        reasons: list[str] = []
        evidence: list[Evidence] = []
        signals: list[float] = []
        cold = False

        # --- deviation vs baseline across the deterministic metrics ----------
        for metric, value, human in (
            ("cost_usd", current_cost, "cost"),
            ("model_calls", float(tr.model_calls), "model calls"),
            ("tool_calls", float(tr.tool_calls), "tool calls"),
            ("retries", float(tr.retries), "retries"),
            ("total_tokens", float(tr.total_input_tokens + tr.total_output_tokens), "tokens"),
            ("latency_ms", float(tr.latency_ms), "latency"),
        ):
            m, z, is_cold = _mult(bp, metric, value)
            cold = cold or is_cold
            if is_cold:
                continue
            if m >= stop_mult:
                signals.append(clamp(0.75 + (m - stop_mult) / (stop_mult * 4)))
                reasons.append(f"{human} is {m:.1f}x the workflow baseline (median).")
                evidence.append(Evidence(kind="baseline", supports_response=False,
                                         detail=f"{metric}={value:g} vs median x{m:.1f}", confidence=0.9))
            elif m >= warn_mult:
                signals.append(clamp(0.3 + (m - warn_mult) / (stop_mult - warn_mult) * 0.35))
                reasons.append(f"{human} is {m:.1f}x the workflow baseline.")
                evidence.append(Evidence(kind="baseline", supports_response=False,
                                         detail=f"{metric}={value:g} vs median x{m:.1f}", confidence=0.85))

        # --- hard structural ceilings from the workflow profile -------------
        if max_tool_calls and tr.tool_calls > max_tool_calls:
            signals.append(0.8)
            reasons.append(f"tool calls {tr.tool_calls} exceed the profile ceiling of {max_tool_calls}.")
        if max_model_calls and tr.model_calls > max_model_calls:
            signals.append(0.75)
            reasons.append(f"model calls {tr.model_calls} exceed the profile ceiling of {max_model_calls}.")

        # --- absolute budget + trajectory ---------------------------------
        over_budget_ratio = projected_cost / budget if budget else 0.0
        if over_budget_ratio >= 3.0:
            signals.append(0.95)
        elif over_budget_ratio >= 1.5:
            signals.append(0.75)
        elif over_budget_ratio >= 1.0:
            signals.append(0.5)
        if over_budget_ratio >= 1.0:
            reasons.append(
                f"Projected cost ${projected_cost:.3f} vs budget ${budget:.2f} "
                f"({over_budget_ratio:.1f}x){' — trajectory ' + trajectory if tr.in_flight else ''}."
            )
            evidence.append(Evidence(kind="baseline", supports_response=False,
                                     detail=f"projected ${projected_cost:.3f} / budget ${budget:.2f}",
                                     confidence=0.9))

        if tr.in_flight and trajectory == "rapidly_increasing":
            signals.append(clamp(0.55 + over_budget_ratio * 0.1))
            reasons.append("Per-step cost is accelerating while the agent is still running.")

        score = max(signals) if signals else 0.0
        # Cost is deterministic: confidence is high when a baseline exists, still
        # solid on cold start because budget comparison is absolute.
        confidence = 0.9 if (not cold and signals) else (0.65 if signals else 0.8)
        label = "ok"
        if score >= 0.75:
            label = "cost_runaway"
        elif score >= 0.35:
            label = "cost_elevated"

        if not signals:
            reasons.append(f"Cost ${current_cost:.4f} is within the expected range for this workflow.")

        return EvaluationResult(
            dimension=Dimension.COST,
            score=round(clamp(score), 4),
            confidence=round(confidence, 4),
            severity=severity_from_score(score),
            label=label,
            reasons=reasons,
            evidence=evidence,
            evaluator=self.name,
            tier=1,
        )
