"""Three-arm benchmark: no-checker vs always-deep vs ControlPlane.

    python scripts/benchmark.py --count 3000
    python scripts/benchmark.py --count 3000 --deep-eval-sim-latency 300

Outputs results/benchmark_report.json and results/benchmark_report.md.
Results are split into structural (deterministic) / runtime-local (this
machine) / simulated-cost (synthetic model) tiers.
"""
from __future__ import annotations

import argparse
import asyncio
import json

import _bootstrap
from _bootstrap import RESULTS_DIR

from app.controlplane.benchmark import run_benchmark


def _row(name, a, b, c):
    return f"| {name} | {a} | {b} | {c} |"


def _to_markdown(r: dict) -> str:
    s = r["structural"]
    rl = r["runtime_local"]
    sc = r["simulated_cost"]
    A, B, C = s["A_no_checker"], s["B_always_deep"], s["C_controlplane"]
    lines = [
        "# ControlPlane.ai - Benchmark Report",
        "",
        f"_Synthetic ground truth. {r['label']}. Wall time {r['wall_time_s']}s. "
        f"deep_eval_sim_latency_ms = {r['deep_eval_sim_latency_ms']:g}._",
        "",
        "## Tier 1 - Structural metrics (deterministic, machine-independent) -- THE HEADLINE",
        "",
        "| Metric | A: no checker | B: always deep | C: ControlPlane |",
        "| --- | --- | --- | --- |",
        _row("recall", A["recall"], B["recall"], C["recall"]),
        _row("precision", A["precision"], B["precision"], C["precision"]),
        _row("false positive rate", A["false_positive_rate"], B["false_positive_rate"], C["false_positive_rate"]),
        _row("false negatives", A["false_negatives"], B["false_negatives"], C["false_negatives"]),
        _row("fast-path %", A["fast_path_pct"], B["fast_path_pct"], C["fast_path_pct"]),
        _row("deep-eval %", A["deep_eval_pct"], B["deep_eval_pct"], C["deep_eval_pct"]),
        _row("intervention %", A["intervention_pct"], B["intervention_pct"], C["intervention_pct"]),
        "",
        f"- recall retained vs always-deep: **{s['recall_retained_vs_always_deep']}**",
        f"- false-positive-rate delta vs always-deep: **{s['fpr_delta_vs_always_deep']}**",
        f"- no-ground-truth handling: {s['uncertainty_handling']['no_ground_truth_cases']} cases, "
        f"confidence-lowered {s['uncertainty_handling']['confidence_lowered_rate']}, "
        f"high-impact-escalated {s['uncertainty_handling']['high_impact_escalated_rate']}",
        "",
        "**Safe claim:** " + r["north_star"]["claim"],
        "",
        "## Tier 2 - Measured local runtime (THIS machine, mock evaluators; not portable)",
        "",
        f"_{rl['note']}_",
        "",
        "| Metric | B: always deep | C: ControlPlane |",
        "| --- | --- | --- |",
        f"| measured p50 overhead ms | {rl['B_always_deep']['measured_p50_overhead_ms']} | {rl['C_controlplane']['measured_p50_overhead_ms']} |",
        f"| measured p95 overhead ms | {rl['B_always_deep']['measured_p95_overhead_ms']} | {rl['C_controlplane']['measured_p95_overhead_ms']} |",
        f"| p95 with +{r['deep_eval_sim_latency_ms']:g}ms sim deep latency | "
        f"{rl['B_always_deep']['illustrative_p95_with_sim_deep_latency_ms']} | "
        f"{rl['C_controlplane']['illustrative_p95_with_sim_deep_latency_ms']} |",
        "",
        f"- measured p95 overhead reduction vs always-deep: **{rl['p95_overhead_reduction_vs_always_deep_measured']}** "
        "(noisy; machine-dependent)",
        f"- {rl['expected_added_latency_formula']}",
        "",
        "## Tier 3 - Simulated cost (synthetic compute-unit model, NOT dollars)",
        "",
        f"_{sc['note']}_",
        "",
        f"- unit price (illustrative): ${sc['unit_price_usd']}",
        f"- mean checker cost/request: always-deep ${sc['B_always_deep']['mean_checker_cost_usd']:.2e} "
        f"vs ControlPlane ${sc['C_controlplane']['mean_checker_cost_usd']:.2e}",
        f"- checker-work reduction vs always-deep: **{sc['checker_work_reduction_vs_always_deep']}** "
        "(depends on the relative cost_units assigned to evaluators)",
    ]
    ns = r["north_star"]
    if "learning_effect" in ns:
        le = ns["learning_effect"]
        lines += [
            "",
            "## Learning effect (SIMULATION)",
            "",
            f"- deep-check rate before validated patterns: **{le['before']['deep_check_rate']:.1%}** "
            f"(recall {le['before']['recall']})",
            f"- deep-check rate after validated patterns: **{le['after']['deep_check_rate']:.1%}** "
            f"(recall {le['after']['recall']})",
            f"- {le['note']}",
        ]
    return "\n".join(lines) + "\n"


async def _main(count: int, seed: int, profile: str, sim_latency: float) -> None:
    result = await run_benchmark(count=count, seed=seed, profile=profile,
                                 deep_eval_sim_latency_ms=sim_latency)
    (RESULTS_DIR / "benchmark_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (RESULTS_DIR / "benchmark_report.md").write_text(_to_markdown(result), encoding="utf-8")
    print(_to_markdown(result))
    print("Wrote results/benchmark_report.json and .md")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--profile", default="mixed")
    ap.add_argument("--deep-eval-sim-latency", type=float, default=0.0,
                    help="ms to add per deep evaluation (illustration of a real network deep path)")
    a = ap.parse_args()
    asyncio.run(_main(a.count, a.seed, a.profile, a.deep_eval_sim_latency))
