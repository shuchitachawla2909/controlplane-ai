# ControlPlane.ai — Limitations

Intellectual honesty improves credibility. This is a **Round 2 prototype on
synthetic data**, not production enterprise software.

## What ControlPlane cannot do

- **It cannot universally prove factual truth.** With no authoritative source,
  no retrieved context and no validated case, it represents *uncertainty*
  (medium risk, low confidence) — it does not decide the answer is false. An
  optional Tier-2 LLM judge is explicitly **down-weighted** in this regime so it
  cannot flip the state to "asserted false".
- **The performance capability is structured-fact + lexical grounding, not
  semantic fact-checking.** A contradiction phrased *verbally* with no number and
  no structured fact is **not caught** by Tier 1 — the blind challenge set
  (`docs/evaluation.md`) reports these as misses (`bp01`, `bp02`, `bp20`,
  `bp21`). A future optional Tier-2 semantic check is the right place for them.
- **The conflicting-evidence check is deliberately conservative.** It compares
  numbers that share a unit or are large magnitudes; genuinely conflicting
  *small unitless quantities* ("18 vs 22 days", "3–5 vs 7–10 days") are missed
  (`bce01`, `bce02`) because loosening the check re-introduced false positives on
  ranges and version-number boilerplate. The explicit
  `risk_signals=["conflicting_evidence"]` tracing hook always fires.
- **The structured-fact check has a false-positive class:** a *correct* answer
  that states the trusted value **and** a contrasting value for a different
  sub-case ("senior 60 days, junior 30") can be over-flagged (`bn03`).
- **User feedback is noisy and gameable.** Raw feedback never modifies critical
  behaviour; trust tiers, de-duplication, minimum evidence counts and human
  confirmation guard the learning loop, but they do not eliminate the risk.
- **PII detection is imperfect.** Without Microsoft Presidio, ControlPlane only
  claims high-precision patterns (email, phone, card/identifier, secrets) and
  reports PERSON / contextual-financial detection as *unavailable* rather than
  guessing. Presidio itself is not perfect.
- **Bias detection from single outputs is weak.** The lexical signal catches
  explicit generalizations only; the counterfactual probe uses a single
  substituted pair and reports a *difference signal*, not statistical fairness.
  Robust fairness evaluation needs broader data and domain-specific analysis.
- **LLM-as-judge can be wrong.** It is optional, Tier 2 only, never on the fast
  path, capped in confidence, and never asked for chain-of-thought. Default is a
  deterministic mock.
- **Statistical baselines need data.** Cold-start workflows report LOW baseline
  confidence and are treated conservatively for high-impact workflows; they are
  not reliable until enough normal traffic is observed.

## What the numbers do and don't mean

- **Two evaluation suites, reported separately.** The **regression suite** (186
  cases) is co-designed with the detectors — near-perfect precision/recall on the
  injected dimensions is expected *by construction* and only guards against
  regressions; the one independent signal is the 0.00 false-positive rate on the
  62 clean-normal cases. The **blind challenge set** (~43 independently authored
  cases, frozen, detectors not tuned against it) is the honest number:
  action-in-range ≈ **0.63**, hard-negative false-positive rate ≈ **0.12**,
  performance recall ≈ **0.38** on unambiguous cases. It is **not** a formal
  unbiased benchmark.
- **Risk scores are interpretable decision scores, not calibrated
  probabilities.** There is no calibration curve; a `performance_risk` of 0.7 is
  not "70% likely wrong".
- **Benchmark results do not represent real enterprise traffic.** Class mix,
  anomaly rates and model costs are illustrative prototype assumptions. Arm A
  (no checker) recall 0 is definitional, not a finding.
- **Latency numbers are laptop + mock-evaluator numbers** and are reported in a
  clearly-labelled "runtime-local" tier. Real overhead depends on deployment and
  the deep evaluators chosen; absolute milliseconds vary run-to-run. The
  `--deep-eval-sim-latency` run is an *illustration* of a real deep path. The
  portable claim is structural: C adds deep-path latency on ~6% of traffic vs
  100% for always-deep.
- **Simulated checker cost is a synthetic compute-unit model, not dollars.** The
  ~0.84 "checker-work reduction" is an artifact of the relative `cost_units`
  assigned to evaluators; the direction is defensible, the figure is not a
  financial estimate.
- **"Prevented spend" is a projection**, not a ledger: `projected − incurred`,
  where `projected` is a trajectory extrapolation that can exceed the sum of a
  scenario's own defined steps. Labelled a simulation everywhere it appears.
- **The learning-effect benchmark injects trusted patterns** rather than running
  the full feedback→validation DB flow; it is labelled a simulation. (The real
  DB flow *is* tested end-to-end in `test_learning_loop.py`.)

## Scope boundaries

- ControlPlane is **not** a replacement for authorization, IAM, API
  authentication, database authorization, model-provider safety, or enterprise
  data governance. The application/team still owns those.
- It is **not** a regulatory compliance engine. Regulation varies by geography
  and industry and requires domain-specific legal review.
- **SQLite / single-process is prototype scope.** The design scales (stateless
  evaluators, bounded baseline windows, O(#findings) routing); a real deployment
  would be stateless workers + Postgres + a policy service.
- The prototype deliberately avoids Kubernetes, Kafka, microservices, external
  databases and any mandatory paid API. A production deployment would add
  configurable data retention, field-level capture controls, stronger
  privacy/security controls, real OTLP export, and horizontal scale-out — none
  of which change the core adaptive-decision design.

## Data the checker stores

- With `CONTROLPLANE_STORE_RAW=false` (**default**), persisted trace/decision
  records store **redacted** request/response text (email / phone / card /
  secret / "Name Name's" masked); detected entity **types and counts** are kept
  for audit. The live API response to the immediate caller is not redacted
  (transient). Raw storage is a deliberate opt-in for a deployment with its own
  retention controls.
- A bare number that is not part of a recognised pattern (e.g. a salary figure
  without a currency symbol) is **not** masked — the regex redactor is
  high-precision, not entity recognition.

## Known rough edges in the prototype

- The Tier-1 grounding check is token-overlap based; heavy paraphrase can push a
  correct answer below threshold, at which point the router *may* spend a Tier-2
  TF-IDF check on it (a cost, not a wrong answer). The Tier-2 TF-IDF check and a
  hedged-answer style similarly cost a Tier-2 pass.
- Interaction signatures for the learning loop are coarse (`workflow:intent`);
  two genuinely different questions sharing an intent bucket would share a
  pattern. `MIN_TRUSTED_EVIDENCE = 1` — one human validation promotes a pattern.
- `GoldenCaseRow` (validated corrected answers) is written by the learning loop
  but **not yet read** by any evaluator — the quality baseline is a store, not
  yet a mechanism (roadmap item).
- The counterfactual bias evaluator's mock generation is deterministic and
  simplistic; it demonstrates the mechanism, not production fairness testing, and
  rarely fires on the normal routing path.
- `adapters/otel.py` and `sdk/client.py` are illustrative seams — not imported by
  the running system.
