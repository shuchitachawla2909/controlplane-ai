# ControlPlane.ai — Decision Engine

Nothing about a decision is hard-coded across the codebase. Thresholds,
human-review rules and data policy come from **versioned YAML**
(`config/policies`, `config/workflows`); every decision records the exact
`policy_version` it ran under.

---

## 1. Signals → evidence → risk → routing → action

```
Tier 0 observe
  → Tier 1 evaluators (7, dispatched together)  ── each returns EvaluationResult
        {dimension, score(risk 0..1), confidence 0..1, severity, label,
         reasons[], evidence[], evaluator_version, proposed_safe_response?}
  → Risk engine (per dimension + overall)
  → route(): is deeper verification worth the latency/compute?
  → [Tier 2 evaluators if worth it]
  → decide(): decision matrix + explicit rules
  → intervention + audit record
```

### Evaluators (all behind one interface, `evaluators/base.py`)

| Evaluator | Tier | Dimension | Method (no hidden chain-of-thought) |
| --- | --- | --- | --- |
| `grounding_v1` | 1 | performance | authoritative structured-fact contradiction (strongest) + token-overlap grounding + explicit no-ground-truth handling. **Not** semantic fact-checking — verbal contradictions are missed (see blind set). |
| `conflicting_evidence_v1` | 1 | performance | contradictory values for the same concept across retrieved chunks (or an explicit `risk_signals` marker) → MEDIUM risk, **LOW confidence** (uncertainty). Conservative: ≥2 chunks, comparable units/magnitudes, shared non-structural concept word; zero on ordinary multi-chunk retrieval. |
| `cost_v1` | 1 | cost | deterministic: token/model-call/tool-call/retry/latency deviation vs robust baseline + budget + trajectory. **No LLM.** |
| `failure_pattern_v1` | 1 | performance | lookup against *trusted* validated failure patterns (learning loop) |
| `pii_pattern_v1` / `pii_presidio_v1` | 1 | responsibility | Presidio when installed; otherwise **high-precision patterns only** (email/phone/card/secret) and PERSON/financial reported *unavailable* |
| `responsibility_v1` | 1 | responsibility | unsafe-content patterns, secret disclosure, confidential-marking leak, forbidden entities |
| `bias_lexical_v1` | 1 | responsibility | explicit group-generalization signal (secondary capability; honest about limits) |
| `grounding_tfidf_v1` | 2 | performance | sentence-level TF-IDF cosine vs retrieved context |
| `llm_judge_v1` | 2 | performance | optional LLM-as-judge (mock by default), structured `{score,label,reason,confidence}`. **Down-weighted** by `risk_engine._dampen_unfounded_judge` when there is no ground truth and no retrieval context — it may stay as supporting evidence but cannot drive the dimension or flip the state to "asserted false". |
| `bias_counterfactual_v1` | 2 | responsibility | controlled demographic substitution, reports a *difference signal* not a fairness proof. Rarely on the normal path (a clear `bias_signal` escalates without Tier 2). |

---

## 2. Risk engine (`controlplane/risk_engine.py`)

Risk and **confidence that the risk assessment is correct** are kept separate,
per dimension. The dimensions are **not averaged**.

For each dimension `d ∈ {performance, cost, responsibility}`:

```
risk[d]        = max(score of findings in d)             # interpretable: strongest single finding
confidence[d]  = confidence(top finding) + 0.05·(corroborating findings)
severity[d]    = max severity among findings in d
```

Context:

```
impact   = business_impact of the workflow profile (low / medium / high)
novelty  = clamp((max robust-z across operational metrics − 3) / 6)   # known patterns cap it at 0.3
baseline_confidence = min(baseline confidence across core metrics)     # LOW on cold start
```

Aggregation (documented, not hidden):

```
severity_mult = {none:0.6, low:0.8, medium:1.0, high:1.15, critical:1.3}
impact_mult   = {low:0.9, medium:1.0, high:1.15}

adjusted[d]   = clamp( risk[d] × severity_mult[severity[d]] × impact_mult × max(confidence[d], 0.05) )

overall_risk  = max(adjusted[d] for d)
# cross-risk escalation: if ≥ 2 dimensions have raw risk ≥ 0.5
overall_risk  = clamp(overall_risk + 0.15)
```

Worked example:

```
performance = 0.10 (conf 0.8)     responsibility = 0.95 (conf 0.9, critical)
cost        = 0.08 (conf 0.9)     impact = medium
adjusted_responsibility = 0.95 × 1.3 × 1.0 × 0.9 = 1.0 (clamped)
overall_risk = 1.0   ← stays high; NOT dragged down by an average
```

Compounding risk (`inherited_risk ≥ 0.35`, read from `trace.metadata` **and** the
terminal step): if inherited > own performance risk it passes through undecayed
(the session layer owns decay); if the turn also generates its own risk ≥ 0.35
the two **compound** (`max(own, inherited) + 0.10`); performance confidence is
capped at 0.55; `consequential_action` forces `impact = high`.

---

## 3. Routing — "is verification worth it?" (`policy_engine.route`)

The central question is **not** "is this risky?" but **"is additional
verification worth the latency and compute for this interaction?"**

```
raw = max(risk.performance, risk.cost, risk.responsibility)

# clear-cut, act now — no Tier 2:
if responsibility.risk ≥ block_thr and confidence ≥ min_conf_for_block → escalate
if cost.risk ≥ 0.75 and confidence ≥ 0.8                              → escalate

# clearly low risk:
if raw < fast_path_below (≈0.30)                                      → fast path

# otherwise, an interpretable verification-value score:
verification_value = 0.40·raw
                   + 0.30·raw·(1 − overall_confidence)   # verifying helps most when risky AND unsure
                   + 0.20·impact_weight                  # low .3 / med .6 / high 1.0
                   + 0.10·novelty
if latency budget tight and raw < 0.6 and impact ≠ high → verification_value −= 0.15 (prefer async)
if novelty ≥ novelty_force_verify → verification_value = max(…, verify_value_threshold)

verify   = verification_value ≥ verify_value_threshold (≈0.45)
escalate = raw ≥ escalate_threshold and overall_confidence ≥ 0.6
```

A **trusted failure pattern is itself the corroboration** — when
`known_failure_pattern` is present with high confidence, ControlPlane escalates
and acts *without* re-running Tier 2 (`router._already_corroborated`).

---

## 4. Decision matrix (`policy_engine.decide`)

Applied in order; the first rule that fires wins.

| # | Condition | Action |
| --- | --- | --- |
| 1 | responsibility.risk ≥ block & conf ≥ min_conf; **PII only**, redactable, non-secret/unsafe, and `data_policy.pii_action[class] == redact` | **MODIFY** (deterministic redaction) |
| 1 | responsibility.risk ≥ block & conf ≥ min_conf; secret / unsafe / bias_signal, or `pii_action[class] == block` (confidential/restricted) | **BLOCK** |
| 1 | redact ≤ responsibility.risk < block & conf ≥ 0.5; PII redactable | **MODIFY** (redaction) |
| 2 | cost runaway (label / projected ≥ stop_mult·expected / projected > budget) & conf ≥ 0.6 | **STOP_EXECUTION** (in-flight) / **BLOCK** (completed) |
| 3 | no ground truth & performance.risk ≥ verify & conf < 0.5 & impact = high | **HUMAN_REVIEW** or **SAFE_FALLBACK** |
| 3b | consequential agent action + unresolved inherited risk + conf < 0.75 | **HUMAN_REVIEW** or **SAFE_FALLBACK** |
| 4 | authoritative contradiction & conf ≥ 0.7 & trusted statement available | **MODIFY** (trusted-source reconstruction) |
| 4 | authoritative contradiction & conf ≥ 0.7 & high impact | **HUMAN_REVIEW** |
| 4b | `conflicting_evidence` or `inherited_risk` label present, no own hard violation, not consequential, perf.risk ≥ verify & perf.conf ≤ 0.6 | **VERIFY** (pre-Tier-2) / **MONITOR** (post) — so the unresolved risk is tracked and, in a session, propagates |
| 5 | Matrix on `overall_risk` band × evidence-confidence band | ALLOW / MONITOR / VERIFY / SAFE_FALLBACK / BLOCK / HUMAN_REVIEW |
| 6 | high impact + unresolved uncertainty (overall_risk ≥ 0.4, conf < 0.5) & action was ALLOW/MONITOR | **HUMAN_REVIEW** (override) |

Band map: `<0.25 low`, `<0.5 medium`, `<0.75 high`, `else critical`.
Confidence "high" = evidence_confidence ≥ 0.6.

### MODIFY is never an LLM rewrite (clarification #7)

`MODIFY` uses one of:
- **deterministic redaction** — replace detected spans with `[REDACTED_<TYPE>]`;
- **trusted-source reconstruction** — emit the verified statement attached to the
  authoritative fact (e.g. *"Returns are accepted within 30 days of delivery."*);
- **safe fallback** — a fixed "could not verify, consult the official source"
  message.

---

## 5. Audit record

Every decision produces a `DecisionRecord` with: component risks + confidences,
`severity/impact/novelty`, `overall_risk`, `ground_truth_available`,
`inherited_risk`, `consequential_action`, `data_classification`,
`tiers_run`, `evaluators_run`, `verification_value`, `action`, `reasons[]`,
the five explainability strings, `policy_name` + `policy_version`,
`original_response` (+ `original_response_redacted`) vs `safe_response`,
`projected_cost / cost_budget / prevented_spend`, and latency accounting
(`controlplane_overhead_ms`, `sequential_check_ms` = summed per-check time,
`parallel_check_ms` = dispatch wall time, `synchronous`).

**Persistence:** with `CONTROLPLANE_STORE_RAW=false` (default) the persisted
`trace_json` and `record` have request/response text **redacted**; detected
entity types/counts are retained for audit. The live API response to the
immediate caller is not redacted.
