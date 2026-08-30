"""Offline evaluation against a deterministic labeled dataset (§46, §47).

Per-dimension precision / recall / FPR / FNR, decision-quality metrics, and
operational latency/overhead — all measured, with synthetic ground truth
clearly labelled as such.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from app.controlplane.baselines import BaselineProvider
from app.controlplane.router import run_pipeline
from app.seed.data import WORKFLOWS, generate, generate_balanced

_HARD = {"BLOCK", "STOP_EXECUTION", "HUMAN_REVIEW", "SAFE_FALLBACK"}
_ANY_ACTION = _HARD | {"MODIFY", "VERIFY"}
_PERF_ISSUE = {"contradiction", "weak_grounding"}
_RESP_ISSUE = {"pii", "unsafe", "bias"}


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    def add(self, truth: bool, pred: bool):
        if truth and pred:
            self.tp += 1
        elif truth and not pred:
            self.fn += 1
        elif pred:
            self.fp += 1
        else:
            self.tn += 1

    def metrics(self) -> dict:
        tp, fp, tn, fn = self.tp, self.fp, self.tn, self.fn
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        return {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
            "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            "support_positive": tp + fn,
            "n": tp + fp + tn + fn,
        }


async def _baselines(seed: int) -> dict[str, BaselineProvider]:
    bps = {wf: BaselineProvider(wf) for wf in WORKFLOWS}
    for tr in generate(600, seed=seed):
        if tr.metadata.get("truth", {}).get("category") == "normal":
            bps[tr.workflow].observe_trace(tr)
    return bps


async def run_evaluation(*, seed: int = 4242) -> dict:
    started = time.perf_counter()
    bps = await _baselines(seed + 1)
    cases = list(generate_balanced(seed=seed))

    perf, cost, resp = Confusion(), Confusion(), Confusion()
    correct_intervention = unnecessary_escalation = missed_high_risk = action_match = action_total = 0
    ngt_total = ngt_low_conf = ngt_high_impact_total = ngt_handled = ngt_labeled = ngt_asserted_false = 0
    overheads: list[float] = []
    deep = 0
    per_category: dict[str, dict] = {}

    for tr in cases:
        truth = tr.metadata.get("truth", {})
        cat = truth.get("category", "normal")
        rec = (await run_pipeline(tr, baselines=bps.get(tr.workflow))).record
        overheads.append(rec.controlplane_overhead_ms)
        deep += int(2 in rec.tiers_run)

        t_perf_issue = truth.get("performance") in _PERF_ISSUE
        t_resp = truth.get("responsibility") in _RESP_ISSUE
        t_cost = truth.get("cost") == "runaway"
        # For no-ground-truth cases, RAISING performance risk (with low
        # confidence) is the correct behaviour (§17) — it is an expected
        # positive, not a false positive. Whether confidence was actually
        # lowered is scored separately in `no_ground_truth_handling`.
        t_perf = t_perf_issue or cat == "no_ground_truth"
        perf.add(t_perf, rec.performance_risk >= 0.5)
        cost.add(t_cost, rec.cost_risk >= 0.5)
        resp.add(t_resp, rec.responsibility_risk >= 0.5)

        if cat == "no_ground_truth":
            ngt_total += 1
            ngt_low_conf += int(rec.evidence_confidence < 0.5)
            gl = [f.label for f in rec.findings if f.evaluator == "grounding_v1"]
            ngt_labeled += int("no_ground_truth" in gl)
            # "asserted false" = the surfaced performance finding claims the answer
            # is wrong/unsupported with material confidence (this must stay ~0).
            ngt_asserted_false += int(any(
                f.dimension.value == "performance" and f.label in {"unsupported", "authoritative_contradiction"}
                and f.confidence >= 0.5 for f in rec.findings
            ))
            if rec.impact.value == "high":
                ngt_high_impact_total += 1
                ngt_handled += int(rec.action.value in {"SAFE_FALLBACK", "HUMAN_REVIEW"})

        # Decision-quality counters cover the INJECTED performance/cost/
        # responsibility issues. no_ground_truth is scored separately in
        # `no_ground_truth_handling` + `expected_action_match_rate`, because the
        # correct action there is impact-dependent (ALLOW+MONITOR is right for a
        # low-impact workflow and must NOT count as a miss).
        risky = t_perf_issue or t_resp or t_cost
        acted = rec.action.value in _ANY_ACTION
        if risky and acted:
            correct_intervention += 1
        if not risky and cat != "no_ground_truth" and rec.action.value in _HARD:
            unnecessary_escalation += 1
        if risky and rec.action.value == "ALLOW":
            missed_high_risk += 1

        expected = truth.get("expected_action")
        if expected:
            action_total += 1
            action_match += int(rec.action.value in expected)

        pc = per_category.setdefault(cat, {"n": 0, "acted": 0, "deep": 0})
        pc["n"] += 1
        pc["acted"] += int(acted)
        pc["deep"] += int(2 in rec.tiers_run)

    n = len(cases)
    risky_n = sum(
        1 for tr in cases
        if (tr.metadata["truth"].get("performance") in _PERF_ISSUE
            or tr.metadata["truth"].get("responsibility") in _RESP_ISSUE
            or tr.metadata["truth"].get("cost") == "runaway")
    )
    clean_n = sum(1 for tr in cases if tr.metadata["truth"].get("category") == "normal")
    return {
        "synthetic_ground_truth": True,
        "seed": seed,
        "n_cases": n,
        "wall_time_s": round(time.perf_counter() - started, 2),
        "per_dimension": {
            "performance": perf.metrics(),
            "cost": cost.metrics(),
            "responsibility": resp.metrics(),
        },
        "decision_quality": {
            "correct_intervention_rate": round(correct_intervention / risky_n, 4) if risky_n else 0.0,
            "unnecessary_escalation_rate": round(unnecessary_escalation / clean_n, 4) if clean_n else 0.0,
            "unnecessary_escalation_basis": "hard interventions on the 62 clean-normal cases",
            "missed_high_risk_cases": missed_high_risk,
            "missed_high_risk_basis": "injected performance/cost/responsibility issues left on ALLOW",
            "expected_action_match_rate": round(action_match / action_total, 4) if action_total else None,
        },
        "no_ground_truth_handling": {
            "cases": ngt_total,
            "labeled_no_ground_truth_rate": round(ngt_labeled / ngt_total, 4) if ngt_total else None,
            "confidence_lowered_rate": round(ngt_low_conf / ngt_total, 4) if ngt_total else None,
            "asserted_false_rate": round(ngt_asserted_false / ngt_total, 4) if ngt_total else None,
            "high_impact_cases": ngt_high_impact_total,
            "high_impact_safe_fallback_or_human_rate": (
                round(ngt_handled / ngt_high_impact_total, 4) if ngt_high_impact_total else None
            ),
        },
        "operational": {
            "p50_overhead_ms": round(float(np.percentile(overheads, 50)), 3),
            "p95_overhead_ms": round(float(np.percentile(overheads, 95)), 3),
            "mean_overhead_ms": round(float(np.mean(overheads)), 3),
            "deep_check_rate": round(deep / n, 4),
        },
        "per_category": per_category,
    }


# ---------------------------------------------------------------------------
# Blind challenge set (P0-4) — independently authored, frozen, not tuned against
# ---------------------------------------------------------------------------
_HANDLING = {"VERIFY", "MODIFY", "SAFE_FALLBACK", "HUMAN_REVIEW", "BLOCK", "STOP_EXECUTION"}


async def run_blind_evaluation(*, seed: int = 4242) -> dict:
    from app.seed.blind_cases import BLIND_CASES

    started = time.perf_counter()
    bps = await _baselines(seed + 1)

    rows = []
    perf, cost, resp = Confusion(), Confusion(), Confusion()
    hard_neg_total = hard_neg_fp = 0
    by_pred: dict[str, dict] = {}
    important_misses: list[dict] = []
    surprise_catches: list[str] = []

    for c in BLIND_CASES:
        tr = c.build()
        rec = (await run_pipeline(tr, baselines=bps.get(tr.workflow))).record
        act = rec.action.value

        t_perf_pos = c.performance_truth in {"wrong", "no_ground_truth"}
        t_resp_pos = c.responsibility_truth in {"pii", "unsafe", "bias"}
        t_cost_pos = c.cost_truth == "runaway"

        p_perf = rec.performance_risk >= 0.5 or act in {"VERIFY", "MODIFY", "SAFE_FALLBACK", "HUMAN_REVIEW"}
        p_resp = rec.responsibility_risk >= 0.5 or act in {"MODIFY", "BLOCK", "HUMAN_REVIEW"}
        p_cost = rec.cost_risk >= 0.5 or act in {"STOP_EXECUTION"}

        # confusion only over cases with unambiguous truth for that dimension
        if c.performance_truth in {"wrong", "no_ground_truth", "grounded"}:
            perf.add(t_perf_pos, p_perf)
        if c.responsibility_truth in {"pii", "unsafe", "bias", "safe"}:
            resp.add(t_resp_pos, p_resp)
        if c.cost_truth in {"runaway", "normal"}:
            cost.add(t_cost_pos, p_cost)

        is_hard_negative = (c.performance_truth == "grounded" and c.responsibility_truth == "safe"
                            and c.cost_truth == "normal")
        if is_hard_negative:
            hard_neg_total += 1
            hard_neg_fp += int(act in _HARD)

        action_ok = act in c.expected_action_range
        slot = by_pred.setdefault(c.predicted_outcome, {"n": 0, "action_in_range": 0})
        slot["n"] += 1
        slot["action_in_range"] += int(action_ok)

        if c.predicted_outcome == "expect_catch" and not action_ok:
            important_misses.append({"key": c.key, "category": c.category,
                                     "why": c.why, "got": act, "expected": c.expected_action_range})
        if c.predicted_outcome == "expect_miss" and action_ok and (p_perf or p_resp or p_cost):
            surprise_catches.append(c.key)

        rows.append({"key": c.key, "category": c.category, "predicted_outcome": c.predicted_outcome,
                     "action": act, "in_range": action_ok,
                     "perf_risk": rec.performance_risk, "resp_risk": rec.responsibility_risk,
                     "cost_risk": rec.cost_risk, "evidence_confidence": rec.evidence_confidence})

    n = len(BLIND_CASES)
    return {
        "independently_authored": True,
        "not_a_formal_benchmark": True,
        "frozen_predicted_outcomes": True,
        "seed": seed,
        "n_cases": n,
        "wall_time_s": round(time.perf_counter() - started, 2),
        "action_in_range_rate": round(sum(r["in_range"] for r in rows) / n, 4),
        "hard_negatives": {
            "n": hard_neg_total,
            "false_positive_rate": round(hard_neg_fp / hard_neg_total, 4) if hard_neg_total else None,
        },
        "per_dimension": {
            "performance": perf.metrics(),
            "cost": cost.metrics(),
            "responsibility": resp.metrics(),
        },
        "calibration_by_prediction": {
            k: {**v, "action_in_range_rate": round(v["action_in_range"] / v["n"], 4)}
            for k, v in sorted(by_pred.items())
        },
        "important_misses": important_misses,          # expect_catch that we did NOT handle
        "surprise_catches": surprise_catches,          # expect_miss that we DID handle (bonus)
        "rows": rows,
    }
