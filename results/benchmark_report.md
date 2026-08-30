# ControlPlane.ai - Benchmark Report

_Synthetic ground truth. 3000 traces / profile=mixed / seed=1729. Wall time 21.93s. deep_eval_sim_latency_ms = 0._

## Tier 1 - Structural metrics (deterministic, machine-independent) -- THE HEADLINE

| Metric | A: no checker | B: always deep | C: ControlPlane |
| --- | --- | --- | --- |
| recall | 0.0 | 0.9317 | 0.9317 |
| precision | 0.0 | 0.8568 | 0.8568 |
| false positive rate | 0.0 | 0.0216 | 0.0216 |
| false negatives | 366 | 25 | 25 |
| fast-path % | 1.0 | 0.0 | 0.9367 |
| deep-eval % | 0.0 | 1.0 | 0.0633 |
| intervention % | 0.0 | 0.1327 | 0.1327 |

- recall retained vs always-deep: **1.0**
- false-positive-rate delta vs always-deep: **0.0**
- no-ground-truth handling: 104 cases, confidence-lowered 1.0, high-impact-escalated 1.0

**Safe claim:** ControlPlane reduces unnecessary deep verification while retaining comparable detection coverage in this controlled benchmark.

## Tier 2 - Measured local runtime (THIS machine, mock evaluators; not portable)

_wall-clock on THIS machine with MOCK evaluators; ratios are indicative, absolute milliseconds are not portable. The 'illustrative_*_with_sim' rows add a hypothetical 0 ms per deep evaluation to model a real (e.g. network LLM) deep path._

| Metric | B: always deep | C: ControlPlane |
| --- | --- | --- |
| measured p50 overhead ms | 3.513 | 0.77 |
| measured p95 overhead ms | 14.227 | 3.521 |
| p95 with +0ms sim deep latency | 14.227 | 3.521 |

- measured p95 overhead reduction vs always-deep: **0.753** (noisy; machine-dependent)
- C adds deep-path latency on ~deep_eval_pct of traffic vs 100% for always-deep; with a deep path costing X ms, expected added latency ~= 0.063*X vs 1.0*X

## Tier 3 - Simulated cost (synthetic compute-unit model, NOT dollars)

_synthetic compute-unit model, NOT production financial savings. cost_units are relative weights (llm_judge=10, tier-1 total ~2.6); unit price is illustrative._

- unit price (illustrative): $2e-05
- mean checker cost/request: always-deep $4.58e-04 vs ControlPlane $7.57e-05
- checker-work reduction vs always-deep: **0.835** (depends on the relative cost_units assigned to evaluators)

## Learning effect (SIMULATION)

- deep-check rate before validated patterns: **6.4%** (recall 0.9345)
- deep-check rate after validated patterns: **3.9%** (recall 1.0)
- Simulation: trusted patterns injected for the failure signatures present in the traffic. Validated patterns let ControlPlane act on known failures earlier, shifting some deep checks to the fast path without losing recall.
