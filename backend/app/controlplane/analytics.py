"""Aggregations for the dashboard metrics endpoints and the CLI reports.

Pure functions over lists of ``DecisionRow`` so the same code powers the API
and the offline scripts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

import numpy as np

from app.core.models import DecisionRow

_INTERVENTION_ACTIONS = {"BLOCK", "STOP_EXECUTION", "HUMAN_REVIEW", "SAFE_FALLBACK", "MODIFY"}
_HARD_INTERVENTIONS = {"BLOCK", "STOP_EXECUTION", "HUMAN_REVIEW", "SAFE_FALLBACK"}


def pct(values: Iterable[float], p: float) -> float:
    arr = np.asarray(list(values), dtype=float)
    return float(np.percentile(arr, p)) if arr.size else 0.0


def overview(decisions: list[DecisionRow], total_spend: float = 0.0) -> dict:
    n = len(decisions)
    if n == 0:
        return {"total_interactions": 0}
    deep = [d for d in decisions if 2 in (d.tiers_run or [])]
    fast = [d for d in decisions if 2 not in (d.tiers_run or [])]
    interventions = [d for d in decisions if d.action in _HARD_INTERVENTIONS]
    return {
        "total_interactions": n,
        "fast_path_rate": round(len(fast) / n, 4),
        "deep_evaluation_rate": round(len(deep) / n, 4),
        "high_risk_interventions": len(interventions),
        "intervention_rate": round(len(interventions) / n, 4),
        "estimated_spend_usd": round(total_spend, 4),
        "prevented_runaway_spend_usd": round(sum(d.prevented_spend_usd for d in decisions), 4),
        "avg_controlplane_overhead_ms": round(float(np.mean([d.controlplane_overhead_ms for d in decisions])), 3),
        "avg_fast_path_overhead_ms": round(
            float(np.mean([d.controlplane_overhead_ms for d in fast])) if fast else 0.0, 3
        ),
        "p95_fast_path_overhead_ms": round(pct((d.controlplane_overhead_ms for d in fast), 95), 3),
        "async_deep_evaluations": sum(1 for d in decisions if not d.synchronous),
        "risk_distribution": {
            "performance": round(float(np.mean([d.performance_risk for d in decisions])), 4),
            "cost": round(float(np.mean([d.cost_risk for d in decisions])), 4),
            "responsibility": round(float(np.mean([d.responsibility_risk for d in decisions])), 4),
        },
        "elevated_counts": {
            "performance": sum(1 for d in decisions if d.performance_risk >= 0.5),
            "cost": sum(1 for d in decisions if d.cost_risk >= 0.5),
            "responsibility": sum(1 for d in decisions if d.responsibility_risk >= 0.5),
        },
        "interventions_by_type": dict(Counter(d.action for d in decisions)),
        "tier_distribution": dict(Counter(d.tier for d in decisions)),
    }


def risk_breakdown(decisions: list[DecisionRow]) -> dict:
    bins = [0.0, 0.15, 0.35, 0.6, 0.85, 1.01]
    labels = ["none", "low", "medium", "high", "critical"]

    def hist(key):
        vals = [getattr(d, key) for d in decisions]
        counts = [0] * len(labels)
        for v in vals:
            for i in range(len(labels)):
                if bins[i] <= v < bins[i + 1]:
                    counts[i] += 1
                    break
        return dict(zip(labels, counts))

    return {
        "performance": hist("performance_risk"),
        "cost": hist("cost_risk"),
        "responsibility": hist("responsibility_risk"),
        "by_severity": dict(Counter(d.severity for d in decisions)),
        "cross_risk_escalations": sum(1 for d in decisions if (d.record or {}).get("cross_risk_escalated")),
    }


def latency_report(decisions: list[DecisionRow]) -> dict:
    fast = [d for d in decisions if 2 not in (d.tiers_run or [])]
    deep = [d for d in decisions if 2 in (d.tiers_run or [])]

    def block(rows):
        return {
            "count": len(rows),
            "p50_overhead_ms": round(pct((r.controlplane_overhead_ms for r in rows), 50), 3),
            "p95_overhead_ms": round(pct((r.controlplane_overhead_ms for r in rows), 95), 3),
            "mean_overhead_ms": round(float(np.mean([r.controlplane_overhead_ms for r in rows])) if rows else 0.0, 3),
            "mean_checks": round(float(np.mean([len(r.evaluators_run or []) for r in rows])) if rows else 0.0, 2),
        }

    summed = [d.sequential_check_ms for d in decisions if d.sequential_check_ms]
    wall = [d.parallel_check_ms for d in decisions if d.parallel_check_ms]
    return {
        "fast_path": block(fast),
        "deep_path": block(deep),
        "all": block(decisions),
        "check_dispatch": {
            # summed per-check time vs the wall time of dispatching them together.
            # The Tier-1 checks are ~0.1 ms total (deterministic CPU), so this is
            # a scheduling detail — NOT a parallel speed-up claim.
            "mean_summed_check_ms": round(float(np.mean(summed)) if summed else 0.0, 3),
            "mean_dispatch_wall_ms": round(float(np.mean(wall)) if wall else 0.0, 3),
            "note": "independent cheap checks dispatched together; expensive verification invoked selectively",
        },
    }


def timeseries(decisions: list[DecisionRow], buckets: int = 12) -> dict:
    if not decisions:
        return {"buckets": []}
    ts = sorted(decisions, key=lambda d: d.created_at)
    t0, t1 = ts[0].created_at, ts[-1].created_at or ts[0].created_at + 1
    span = max(t1 - t0, 1e-6)
    grouped: dict[int, list[DecisionRow]] = defaultdict(list)
    for d in ts:
        b = min(buckets - 1, int((d.created_at - t0) / span * buckets))
        grouped[b].append(d)
    out = []
    for b in range(buckets):
        rows = grouped.get(b, [])
        if not rows:
            continue
        out.append({
            "bucket": b,
            "n": len(rows),
            "mean_performance_risk": round(float(np.mean([r.performance_risk for r in rows])), 3),
            "mean_cost_risk": round(float(np.mean([r.cost_risk for r in rows])), 3),
            "mean_responsibility_risk": round(float(np.mean([r.responsibility_risk for r in rows])), 3),
            "deep_check_rate": round(sum(1 for r in rows if 2 in (r.tiers_run or [])) / len(rows), 3),
            "intervention_rate": round(sum(1 for r in rows if r.action in _HARD_INTERVENTIONS) / len(rows), 3),
        })
    return {"buckets": out}
