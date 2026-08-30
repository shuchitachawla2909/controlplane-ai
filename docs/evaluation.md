# ControlPlane.ai — Evaluation Methodology & Results

All ground truth here is **synthetic or independently authored, and labelled as
such**. Numbers are produced by re-runnable scripts.

```bash
cd backend && ../backend/.venv/Scripts/python ../scripts/run_evaluation.py --suite both
cd backend && ../backend/.venv/Scripts/python ../scripts/benchmark.py --count 3000
cd backend && ../backend/.venv/Scripts/python ../scripts/benchmark.py --count 3000 --deep-eval-sim-latency 300
```

Outputs land in `results/` (JSON + Markdown).

---

## 1. Two evaluation suites — reported separately

### A. Regression suite (controlled, self-consistency) — **not an external benchmark**

`scripts/run_evaluation.py --suite regression` materialises **186 deterministic
cases** to `data/evaluation/dataset.jsonl`. The inputs were **co-designed with
the detectors**: contradiction cases carry a structured fact that differs from a
number in the response; PII cases embed literal email/phone/card patterns;
unsafe/bias cases embed literal trigger phrases; cost cases are built to exceed
the thresholds.

> Near-perfect precision/recall on the injected dimensions is **expected by
> construction** and only demonstrates internal consistency + protects against
> regressions when thresholds or evaluators change. **It is not evidence of
> real-world generalisation.**

The one independent signal in this suite is the **false-positive rate on the 62
clean-normal cases**.

**Results (seed 4242, 186 cases):**

| Dimension | Precision | Recall | FPR | FNR |
| --- | --- | --- | --- | --- |
| Performance | 1.00 | 0.96 | 0.00 | 0.04 |
| Cost | 1.00 | 1.00 | 0.00 | 0.00 |
| Responsibility | 1.00 | 1.00 | 0.00 | 0.00 |

- clean-normal false-positive rate: **0.00** (hard interventions on the 62 clean-normal cases)
- correct-intervention rate (injected issues): **0.98**
- missed high-risk (injected issues left on ALLOW): **2**
- expected-action match rate: **0.91**
- no-ground-truth: labeled `no_ground_truth` **100%**, confidence lowered below 0.5 **100%**,
  ever asserted-false **0%**, high-impact escalated to safe-fallback/human **100%**

### B. Blind challenge set (independently authored) — **not a formal unbiased benchmark**

`scripts/run_evaluation.py --suite blind` runs **~43 cases** authored by
describing situations, *without* reference to detector code
(`backend/app/seed/blind_cases.py`, materialised to
`data/evaluation/blind_dataset.jsonl`). Process:

1. authored, then **frozen**;
2. each case's `predicted_outcome` (`expect_catch` / `expect_miss` / `uncertain`)
   frozen before running;
3. run once, results recorded;
4. **detectors are not tuned to make blind cases pass** — misses are reported.

Categories: paraphrased / verbal contradictions · correct answers with low
lexical overlap · contextual PII (name + salary/health) · regex-visible PII in a
non-confidential workflow · implicit cost drift · borderline / proxy bias ·
adversarial phrasing · unverifiable claims with misleading retrieval · conflicting
retrieved evidence · overlapping risk dimensions · hard negatives / false-positive
traps.

**Results (seed 4242):**

- overall **action-in-expected-range rate: ~0.63**
- **hard-negative false-positive rate: ~0.12** (2 of 17 hard negatives got a hard intervention)
- per-dimension (unambiguous cases only): performance recall ~0.38, responsibility recall ~0.43,
  cost recall 1.0
- calibration: `expect_catch` action-in-range **~0.88**; `expect_miss` **0.0** (we missed all of
  them, exactly as predicted) — our priors were well calibrated

**Important blind misses (honest, unfixed):**

| Case | What it is | Result | Why we don't just patch it |
| --- | --- | --- | --- |
| `bp01/bp02/bp20/bp21` | contradictions phrased **verbally** with no number / structured fact | not flagged (fast path) | Tier 1 grounding is structured-fact + lexical-overlap; verbal contradictions need a semantic evaluator (an optional Tier-2 LLM judge would be the place, not a new regex) |
| `bpii01/bpii02` | **contextual** PII (name + salary / health condition in prose) | not flagged | offline fallback is high-precision patterns only; PERSON / contextual-financial needs Presidio (documented, optional slot) — a fake heuristic would be worse |
| `bce01/bce02` | conflicting retrieved values that are **small unitless quantities** ("18 vs 22 days", "3-5 vs 7-10 days") | not flagged | `ConflictingEvidenceEvaluator` compares numbers with a matching unit or large magnitude; loosening it re-introduced false positives on ranges (9am-6pm) and version-number boilerplate. The explicit `risk_signals=["conflicting_evidence"]` tracing hook still works. |
| `bn03` | a **correct** answer that states the trusted value *and* a contrasting value for a different sub-case ("senior 60 days, junior 30") | over-flagged (MODIFY) | a real, reportable false-positive class in the structured-fact check; candidate for a "value also matched nearby → suppress" guard, out of scope for this phase |

> These are the point of the blind set. The regression suite says the pipeline
> behaves as designed; the blind set says where the deterministic detectors stop.

---

## 2. North-star concept

> **Risk coverage per unit of overhead.** We do not optimise for maximum
> checking — we optimise for maximum risk coverage per unit of latency and
> compute.

---

## 3. Three-arm benchmark — results split into three labelled tiers

`scripts/benchmark.py` runs the same synthetic traffic three ways:

| Arm | Path |
| --- | --- |
| **A — no checker** | AI → user (a no-op reference point; recall 0 is definitional) |
| **B — always deep** | AI → every deep evaluator → user |
| **C — ControlPlane** | AI → cheap checks → *selective* deep checks → user |

`_predicted_risky` = `action ∈ {BLOCK, STOP, HUMAN_REVIEW, SAFE_FALLBACK, MODIFY}`
**or** `overall_risk ≥ 0.5` — i.e. "flagged for attention", reported alongside
`intervention_pct`.

### Tier 1 — Structural metrics (deterministic, machine-independent) — THE HEADLINE

*(3,000 traces, mixed profile, seed 1729)*

| Metric | A: no checker | B: always deep | C: ControlPlane |
| --- | --- | --- | --- |
| recall | 0.00 | 0.93 | **0.93** |
| precision | 0.00 | 0.86 | **0.86** |
| false-positive rate | 0.00 | 0.02 | **0.02** |
| fast-path % | 100% | 0% | **93.7%** |
| deep-eval % | 0% | 100% | **6.3%** |
| intervention % | 0% | ~15% | ~14% |

- **recall retained vs always-deep: 1.00**
- **FPR delta vs always-deep: 0.00**
- no-ground-truth handling (104 cases in the mix): confidence lowered **100%**,
  high-impact escalated **100%**

**Safe claim:** *ControlPlane reduces unnecessary deep verification while
retaining comparable detection coverage in this controlled benchmark.*

### Tier 2 — Measured local runtime (this machine, mock evaluators, **not portable**)

| Metric | B: always deep | C: ControlPlane |
| --- | --- | --- |
| measured p50 overhead | ~4–6 ms | **~0.3–0.9 ms** |
| measured p95 overhead | ~7–9 ms | **~1.3–2.3 ms** |
| p95 with `+300 ms` sim deep latency (illustration) | ~307–309 ms | **~1.5–5 ms** |

Absolute milliseconds swing run-to-run and are dominated by
`sklearn.TfidfVectorizer` micro-timing, not a realistic deep path. The
`--deep-eval-sim-latency 300` run adds a hypothetical 300 ms per deep evaluation
to model a real (network LLM) deep path; there the delta is dominated by the
**deterministic** call count.

**Safe claim:** *C adds deep-path latency on ~6% of traffic vs 100% for
always-deep; with a deep path costing X ms, expected added latency ≈ 0.06·X vs
1.0·X.* (No universal-latency claim.)

### Tier 3 — Simulated cost (synthetic compute-unit model, **not dollars**)

`mean_checker_cost = Σ cost_units × $0.00002`, where `cost_units` are relative
weights (`llm_judge = 10`, Tier-1 total ≈ 2.9) and the unit price is
illustrative.

- checker-work reduction vs always-deep: **~0.84** — an artifact of the assigned
  `cost_units` (raise `llm_judge` to a realistic 100 and it approaches 0.98).
  The *direction* is defensible; the specific figure is not a financial estimate.

### Learning effect (SIMULATION)

`_learning_effect` injects trusted failure patterns for the failure signatures in
the traffic (it does **not** run the real feedback→validation DB flow).

- deep-check rate before validated patterns: **~6.4%** (recall ~0.93)
- deep-check rate after validated patterns: **~3.9%** (recall ~1.00)

Validated patterns let ControlPlane act on known failures without re-running
Tier 2, so oversight cost falls while detection holds.

---

## 4. Alert fatigue / false positives

- Regression suite: `unnecessary_escalation_rate = 0.00` on the 62 clean normals.
- Blind suite: hard-negative FPR **~0.12** — the honest number; over-flagging is
  real on adversarially-shaped negatives.
- Thresholds are per-workflow YAML (`fast_path_below`, `verify_value_threshold`,
  `redact`, `block`, `warn_multiplier`, `stop_multiplier`). A confirmed
  false-positive review verdict cools the matching failure pattern down.
