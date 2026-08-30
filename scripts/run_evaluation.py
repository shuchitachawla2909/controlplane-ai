"""Run the two evaluation suites and write reports.

    python scripts/run_evaluation.py --suite both      # default
    python scripts/run_evaluation.py --suite regression
    python scripts/run_evaluation.py --suite blind

Suites:
  * regression  — the 186 co-designed cases. A controlled self-consistency /
    regression suite. Near-perfect scores on the injected dimensions are
    EXPECTED (cases and detectors share an author). Only meaningful signal:
    zero false positives on the 62 clean-normal cases + regression protection.
  * blind       — ~46 independently authored challenge cases. Not a formal
    benchmark; `predicted_outcome` is frozen; detectors are NOT tuned against
    it. Misses are reported, not fixed.

Outputs:
    results/evaluation_report.json / .md
    data/evaluation/dataset.jsonl          (regression, materialized)
    data/evaluation/blind_dataset.jsonl    (blind, materialized, frozen)
"""
from __future__ import annotations

import argparse
import asyncio
import json

import _bootstrap
from _bootstrap import DATA_DIR, RESULTS_DIR

from app.controlplane.evaluation import run_blind_evaluation, run_evaluation
from app.seed.blind_cases import BLIND_CASES
from app.seed.data import generate_balanced


def _materialize_regression(seed: int = 4242) -> int:
    out = DATA_DIR / "evaluation" / "dataset.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for tr in generate_balanced(seed=seed):
            truth = tr.metadata.get("truth", {})
            fh.write(json.dumps({
                "trace": tr.model_dump(mode="json"),
                "labels": {
                    "performance_truth": truth.get("performance"),
                    "cost_truth": truth.get("cost"),
                    "responsibility_truth": truth.get("responsibility"),
                    "expected_action": truth.get("expected_action"),
                    "category": truth.get("category"),
                },
            }) + "\n")
            n += 1
    return n


def _materialize_blind() -> int:
    out = DATA_DIR / "evaluation" / "blind_dataset.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for c in BLIND_CASES:
            tr = c.build()
            fh.write(json.dumps({
                "trace": tr.model_dump(mode="json"),
                "labels": tr.metadata["blind"],
            }) + "\n")
    return len(BLIND_CASES)


def _regression_md(r: dict) -> str:
    pd = r["per_dimension"]; dq = r["decision_quality"]; op = r["operational"]; ng = r["no_ground_truth_handling"]
    L = [
        "## Regression suite (controlled, self-consistency)",
        "",
        "_186 cases co-designed with the detectors. Near-perfect scores on the injected dimensions "
        "are expected by construction; this suite guards against regressions. The one independent "
        "signal is the false-positive rate on the 62 clean-normal cases._",
        "",
        "| Dimension | Precision | Recall | FPR | FNR | F1 | Support |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in ("performance", "cost", "responsibility"):
        m = pd[d]
        L.append(f"| {d} | {m['precision']} | {m['recall']} | {m['false_positive_rate']} | "
                 f"{m['false_negative_rate']} | {m['f1']} | {m['support_positive']} |")
    L += [
        "",
        f"- clean-normal false-positive rate: **{dq['unnecessary_escalation_rate']}** ({dq['unnecessary_escalation_basis']})",
        f"- correct intervention rate (injected issues): **{dq['correct_intervention_rate']}**",
        f"- missed high-risk (injected issues left on ALLOW): **{dq['missed_high_risk_cases']}**",
        f"- expected-action match rate: **{dq['expected_action_match_rate']}**",
        f"- no-ground-truth: labeled correctly **{ng['labeled_no_ground_truth_rate']}**, "
        f"confidence lowered **{ng['confidence_lowered_rate']}**, asserted-false **{ng['asserted_false_rate']}**, "
        f"high-impact escalated **{ng['high_impact_safe_fallback_or_human_rate']}**",
        f"- p50 / p95 ControlPlane overhead: **{op['p50_overhead_ms']} / {op['p95_overhead_ms']} ms**",
    ]
    return "\n".join(L)


def _blind_md(r: dict) -> str:
    pd = r["per_dimension"]
    L = [
        "## Blind challenge set (independently authored)",
        "",
        f"_{r['n_cases']} cases written without reference to the detector implementations. "
        "Not a formal unbiased benchmark; `predicted_outcome` frozen before running; detectors "
        "not tuned against it. Misses are reported below._",
        "",
        f"- overall action-in-expected-range rate: **{r['action_in_range_rate']}**",
        f"- hard-negative false-positive rate: **{r['hard_negatives']['false_positive_rate']}** "
        f"({r['hard_negatives']['n']} hard negatives)",
        "",
        "| Dimension (unambiguous cases only) | Precision | Recall | FPR | Support |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in ("performance", "cost", "responsibility"):
        m = pd[d]
        L.append(f"| {d} | {m['precision']} | {m['recall']} | {m['false_positive_rate']} | {m['support_positive']} |")
    L += ["", "### Calibration (were our priors right?)", "",
          "| predicted_outcome | n | action-in-range rate |", "| --- | --- | --- |"]
    for k, v in r["calibration_by_prediction"].items():
        L.append(f"| {k} | {v['n']} | {v['action_in_range_rate']} |")
    L += ["", f"### Important misses ({len(r['important_misses'])}) — expect_catch cases we did NOT handle", ""]
    if r["important_misses"]:
        for m in r["important_misses"]:
            L.append(f"- **{m['key']}** ({m['category']}): got `{m['got']}`, expected one of "
                     f"{m['expected']}. {m['why']}")
    else:
        L.append("- (none)")
    if r["surprise_catches"]:
        L += ["", f"### Surprise catches (expect_miss but handled): {', '.join(r['surprise_catches'])}"]
    return "\n".join(L)


async def _main(suite: str) -> None:
    parts = ["# ControlPlane.ai - Evaluation Report", "",
             "Two suites, reported separately. Regression suite != external benchmark. "
             "Blind set != formal unbiased benchmark. All ground truth is synthetic / "
             "independently authored and labelled as such.", ""]
    payload: dict = {}

    if suite in ("regression", "both"):
        nreg = _materialize_regression()
        reg = await run_evaluation()
        payload["regression"] = reg
        parts += [_regression_md(reg), ""]
        print(f"regression: {nreg} cases, "
              f"clean-normal FPR {reg['decision_quality']['unnecessary_escalation_rate']}, "
              f"no-GT labeled {reg['no_ground_truth_handling']['labeled_no_ground_truth_rate']}")

    if suite in ("blind", "both"):
        nbl = _materialize_blind()
        bl = await run_blind_evaluation()
        payload["blind"] = bl
        parts += [_blind_md(bl), ""]
        print(f"blind: {nbl} cases, action-in-range {bl['action_in_range_rate']}, "
              f"hard-negative FPR {bl['hard_negatives']['false_positive_rate']}, "
              f"important misses {len(bl['important_misses'])}")

    (RESULTS_DIR / "evaluation_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (RESULTS_DIR / "evaluation_report.md").write_text("\n".join(parts), encoding="utf-8")
    print("Wrote results/evaluation_report.json and .md")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["regression", "blind", "both"], default="both")
    asyncio.run(_main(ap.parse_args().suite))
