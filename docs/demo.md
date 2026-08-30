# ControlPlane.ai — Demo Script (5–7 minutes)

**Setup:** `docker compose up --build` (or `make setup && make dev`), open
`http://localhost:5173`, and if the Overview page is empty click **"Seed
synthetic demo data"** (or `make seed`). Everything is synthetic; every decision
is computed by the real engine (no hard-coded scenario outcomes). The **Demo
mode** bar on the Overview page runs scenarios A–G + C2 live.

**Show live: B, E, G, Feedback→Learning.** Reference C/C2, D, F on the dashboard.

---

### 0. Framing (30s)

> Enterprises already have models, guardrails, IAM, observability and eval
> tools. The missing decision is *how much oversight each interaction deserves*.
> ControlPlane observes cheaply, estimates **risk and confidence**, spends deep
> verification only where it pays off, acts per workflow policy, and learns from
> validated outcomes.

### 1. Overview (45s)

KPI row: total interactions, **fast-path rate (~93%)**, **deep-eval rate (~6%)**,
prevented (simulated) spend, avg fast-path overhead (sub-ms). Then the
risk-over-time chart.

---

### LIVE 1 — Scenario B, Confidently wrong (75s)

Click **B** → Trace Detail. Evidence panel: ✗ *response states 60 days; trusted
source says 30*. Routing: `verify` → Tier 2 corroborates → **MODIFY** via
`trusted_source_reconstruction`; the released text is the verified statement.

> No LLM rewrite — deterministic reconstruction from the trusted source.
> (Honest boundary: a contradiction phrased *verbally* with no structured fact
> is on our blind-set miss list — Tier 1 is structured-fact + overlap.)

### LIVE 2 — Scenario E, Cost runaway (75s)

Click **E**. Per-step cost `0.01 → 0.02 → 0.04 → 0.08 → 0.15`, budget `$0.10`.
Deterministic `cost_runaway` → **STOP_EXECUTION** (the in-flight step gate stops
at step 2 of 6).

> "Prevented spend" is a **projection under the observed trajectory**, not a
> ledger — labelled as a simulation. Caught from telemetry alone, no LLM.

### LIVE 3 — Scenario G, Multi-turn compounding risk (90s)

Run the session. Show `inherited_risk_trace` rising then sustained (e.g. **`0.0 → 0.5 → 0.5`**), and the final gate on the consequential step:

- **Turn 1** — the answer follows one of two *conflicting* SLA versions →
  `conflicting_evidence` Tier-1 signal (MEDIUM risk, LOW confidence) → **MONITOR**
  (unresolved, not resolved).
- **Turn 2** — "process that refund" → inherits ~0.5 → risk label `inherited_risk`,
  reason cites *"Inherited risk 0.50 carried from an earlier turn"* → **MONITOR**.
- **Turn 3** — the agent's irreversible transfer step (no retrieval context of
  its own) → `inherited_risk ≈ 0.5` + `consequential_action` → **HUMAN_REVIEW**,
  reason: *"consequential / irreversible action while carrying unresolved risk …
  Compounding risk from earlier steps escalated this to human review."*

> The final gate is *because* risk was never resolved — not because turn 3 looks
> dangerous in isolation. This is a general mechanism
> (`ConflictingEvidenceEvaluator` + `sessions.evaluate_session` +
> `risk_engine` inheritance + `decide()` rules 4b/3b), no scenario branching.

### LIVE 4 — Feedback → Learning (75s)

On a flagged trace: **👎 issue** → **Review Queue** (pending) → validate
"incorrect" → *"trusted failure pattern … now influences routing"*. Re-run a
similar question → now **VERIFY/BLOCK** instead of ALLOW. **Learning Loop** page:
evidence pipeline + deep-check-rate chart + before/after tiles (~6.4% → ~3.9%
deep checks, recall held).

---

### Dashboard-only references

- **C / C2 — proportional privacy.** Two rows in Live Monitor: `confidential`
  PII → **BLOCK**; the same leak on an `internal` customer-support interaction →
  **MODIFY** (`[REDACTED_EMAIL_ADDRESS]` released). Data-class driven
  (`data_policy.pii_action`). *Offline detection is high-precision patterns only;
  a name + salary in prose is a documented gap without Presidio.*
- **D — no ground truth.** `ground_truth_available=false`, confidence **0.35**,
  label stays `no_ground_truth` (the mock judge is capped so it can't flip the
  state), action **HUMAN_REVIEW** for the high-impact workflow. *"We lower
  confidence; we do not assert the answer is false."*
- **F — bias.** Explicit stereotype → `bias_signal` → **BLOCK**. (P2: a
  borderline case that routes to the Tier-2 counterfactual probe.)
- **Trace Detail privacy** — the "Original" panel is labelled *"redacted for
  storage"*; persisted records mask email/phone/etc. by default
  (`CONTROLPLANE_STORE_RAW=false`), keeping detected entity **types**.

### 2. Benchmark (60s)

**Performance Benchmark** page → run 1,500. Read the **structural** table
(deterministic): arm A catches nothing; arm B deep-checks 100%; **arm C matches
B's recall at ~94% fast-path and equal FPR**. Note the runtime/cost tiers are
explicitly labelled machine-local / synthetic.

### 3. Close (20s)

> Two evaluations: a controlled regression suite (near-perfect *by construction*)
> and an independently-authored blind set (action-in-range ~0.63, misses
> reported). The value is proportional oversight that scales with risk, not with
> AI traffic.
