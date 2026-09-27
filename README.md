# ControlPlane.ai

### Adaptive Runtime AI Oversight

> **Observe everything. Investigate selectively. Act proportionally. Learn continuously.**

ControlPlane is a **vendor-neutral runtime layer that sits above existing AI
applications** and decides, for every interaction, *how much verification it
deserves and what should happen next* — so oversight scales with **risk**, not
with AI traffic.

This repository is a **working, demonstrable prototype**. It runs fully offline
on synthetic data with **no paid API key**. Every decision in the dashboard is
computed by the real risk engine — nothing is hard-coded per scenario.

- `docs/architecture.md` · `docs/decision_engine.md` · `docs/evaluation.md`
- `docs/demo.md` · `docs/limitations.md` · `docs/research.md`
- Measured results: `results/benchmark_report.md`, `results/evaluation_report.md`

---

## Reviewer Quick Start

Clone the repo and run **one command**. The prototype is fully offline, all data
is synthetic, and **no API key is required**.

### Fastest path — Docker

Prerequisites:
- Docker Desktop with the Linux engine running.

From the repository root:

```bash
docker compose up --build
```

Then open:

- **Dashboard:** http://localhost:5173
- **API docs:** http://localhost:8000/docs

On first boot the backend seeds **1,200 synthetic demo traces**, so the dashboard
is populated right away. No `.env` file is needed — Docker defaults work; to
customise, copy `.env.example` first (`cp` on macOS/Linux, `Copy-Item` on Windows
PowerShell).

### See it work

On the **Overview** page, use the **Demo mode** bar to run scenarios **A–G** live
through the real engine (no per-scenario hard-coding):

- **B** — confidently wrong answer → corrected from a trusted source (`MODIFY`)
- **E** — runaway agent cost → `STOP_EXECUTION` before the budget is breached
- **G** — multi-turn compounding risk → final step escalated to `HUMAN_REVIEW`
- **C / C2** — one PII leak, two data classes → `BLOCK` vs deterministic redaction

Then explore **Live Monitor**, **Trace Detail** (evidence + plain-language
explanation), **Policies**, **Learning Loop**, and **Performance Benchmark**.

### Reproduce the numbers (optional)

From the repository root (interpreter is the project venv; on macOS/Linux use
`backend/.venv/bin/python`):

```bash
make test                                                            # 69 tests
backend/.venv/Scripts/python scripts/run_evaluation.py --suite both  # regression + blind suites
backend/.venv/Scripts/python scripts/benchmark.py --count 3000       # 3-arm benchmark, seed 1729
```

Committed reference outputs: `results/evaluation_report.md`,
`results/benchmark_report.md`.

### Local dev instead of Docker

Requires Python 3.11+, Node 18+, and GNU Make (on Windows, Docker is the
recommended path). Full steps are in the **How to run** section below.

---

## 1. Problem

Every AI deployment carries the same risk: it can be **confidently wrong**,
**quietly expensive**, or **subtly biased / unsafe / leaking data** — usually
discovered only *after* a user has acted on it. Round 2 adds the hard realities:
different use cases have different risk tolerances and latency budgets; bias,
hallucination and privacy overlap; there is often **no real-time ground truth**;
**over-flagging causes alert fatigue** while under-flagging creates liability;
multi-turn agents create **compounding risk**; regulation varies; and enterprises
consume foundation models through APIs and cannot inspect model internals.

## 2. Why existing controls are not enough

Enterprises already have Responsible AI governance,
guardrails, observability, evaluation tooling and IAM. The gap is not "no
governance". The naive Responsible-AI-Checker design —

```
AI response → LLM judge → safety model → bias model → hallucination model → response
```

— adds latency and cost **to every interaction**. Existing tools answer *"can I
observe / evaluate / guard this?"* ControlPlane asks a different question:

> **"Given what I know about this interaction, how much verification does it
> deserve, and what should happen next?"**

It **composes with** those tools (OpenTelemetry, Presidio, Ragas/DeepEval-style
evaluators, NeMo-Guardrails-style concurrent checks, Langfuse-style observation) —
it does not replace them, and it does not replace IAM, API auth, DB
authorization, model-provider safety or data governance.

## 3. Our insight

> **Do not deeply inspect every AI response. Observe every AI execution,
> investigate selectively, act proportionally, and learn continuously.**

The expensive path must be the **exception**. Verification effort is allocated by
an interpretable **verification-priority score** (the implementation variable is
`verification_value`) — a weighted routing heuristic, **not** a formal economic
expected value, a calibrated probability, or a mathematically optimal policy.
Validated outcomes (human / authoritative, not raw feedback) can reduce
unnecessary deep verification over time. *Conceptual claim; demonstrated here as a
synthetic simulation.*

## 4. Solution

An **adaptive funnel** over every AI execution:

```
EVERY AI EXECUTION
   → TIER 0  observe (extremely cheap: telemetry, cost, projected cost)
   → TIER 1  7 cheap deterministic signals, dispatched together (sub-millisecond, local prototype) — performance · cost · responsibility
   → ADAPTIVE RISK ENGINE  risk AND confidence, per dimension + severity/impact/novelty
   → route(): fast path?  verify?  escalate?
   → TIER 2  selective verification (only when it is worth the latency/compute)
   → POLICY  decision matrix (versioned YAML)
   → INTERVENTION  ALLOW · MONITOR · MODIFY · VERIFY · BLOCK · STOP_EXECUTION · HUMAN_REVIEW · SAFE_FALLBACK
   → AUDIT RECORD  + async telemetry
   → FEEDBACK / VALIDATION → trusted evidence → better baselines & routing
```

Five ideas the prototype makes obvious: **adaptive verification budget ·
multi-dimensional evidence · evidence confidence (≠ risk) · risk-aware latency ·
closed-loop learning**.

## 5. Architecture

ControlPlane sits **between AI execution and downstream consumption**:

```
AI app → LLM/RAG/Agent → response → ControlPlane → allow/modify/block/escalate → user
                                              ↘ async telemetry + audit + analytics
```

Full diagrams in [`docs/architecture.md`](docs/architecture.md). Ownership boundary:

| Application / team owns | ControlPlane owns |
| --- | --- |
| authorization, IAM, API auth | standardized observation |
| business rules, allowed actions | cross-dimensional risk assessment |
| data access & classification | adaptive verification routing |
| domain policies, human-approval rules | proportional intervention · audit · learning |

ControlPlane consumes **standardized policy metadata**; it does not learn every
team's business logic.

## 6. Tiered decision engine

| Tier | Role | On the critical path? |
| --- | --- | --- |
| **0 Observe** | normalize trace, count tokens/calls/latency, estimate + project cost. No semantic calls. | always, ~microseconds |
| **1 Cheap signals** | 7 deterministic evaluators, **dispatched together** (`asyncio.gather`): grounding, cost, conflicting-evidence, failure-pattern, PII, responsibility, bias. `asyncio.gather` is a dispatch/scheduling convenience, **not** guaranteed CPU parallelism. | always, sub-millisecond in the local prototype |
| **2 Selective verification** | TF-IDF grounding, optional LLM-judge, counterfactual bias — **only when `verification_value` clears threshold**. Concurrency matters here (an evaluator may do real I/O). | exception (~6% of traffic, measured) |
| **3 Intervention** | block / redact / stop / human review / safe fallback — synchronous for high-risk | exception |

The **verification-priority score** (implementation variable `verification_value`)
is `0.40·risk + 0.30·risk·(1−confidence) + 0.20·impact + 0.10·novelty` (minus a
penalty when the latency budget is tight) — an interpretable weighted heuristic,
per-workflow tunable, **not** an expected-value calculation or a calibrated
probability. Full formula + decision matrix:
[`docs/decision_engine.md`](docs/decision_engine.md).

## 7. Performance ("confidently wrong") detection

The performance capability is **structured-fact contradiction + grounding
coverage + conflicting-evidence + validated-failure lookup** — *not* general
semantic fact-checking. Layered evidence, cheapest first:

1. **Authoritative structured facts** (strongest) — numeric/temporal contradiction
   vs trusted data → e.g. *response says 60 days, policy says 30* → `MODIFY` via
   **trusted-source reconstruction**.
2. **Conflicting retrieved evidence** — deterministic Tier-1 check: contradictory
   values for the same concept across chunks → MEDIUM risk, **LOW confidence**
   (uncertainty, not "wrong").
3. **Retrieved-context grounding** — token overlap (Tier 1), TF-IDF cosine (Tier 2).
4. **Validated historical failure patterns** — from the learning loop.
5. **User feedback** / **human validation** — evidence, not ground truth.

A contradiction phrased **verbally** (no number, no structured fact) is **not
caught by Tier 1** — this is on the blind-set miss list (`docs/evaluation.md`);
the optional Tier-2 LLM judge is the place for it.

**No-ground-truth mode:** when nothing is verifiable, ControlPlane reports
*performance risk MEDIUM, evidence confidence LOW* (hard-capped ~0.25; an
optional LLM judge is down-weighted so it cannot flip the state) and lets impact
decide (`ALLOW+MONITOR` for low impact, `SAFE_FALLBACK`/`HUMAN_REVIEW` for high) —
it never asserts "hallucination = true". Measured on the regression suite: 100%
labelled `no_ground_truth`, 100% confidence-lowered, 0% asserted-false.

## 8. Cost detection

Fully deterministic — **no LLM**. Token / model-call / tool-call / retry /
latency deviation vs a **robust** per-workflow baseline (rolling median, p95,
MAD; anomalies quarantined; cold-start = LOW confidence), plus absolute budget
and **cost trajectory**. An **in-flight agent hook** runs after each step —
`update cumulative cost → project trajectory → CONTINUE | STOP` — and stops
execution **before** the projected cost breaches the budget. "Prevented spend"
is a **projection under the observed trajectory** (projected − incurred), not a
ledger and not a financial estimate — labelled a prototype simulation.

## 9. Responsibility detection

- **PII** — Microsoft Presidio when installed; otherwise **high-precision
  patterns only** (email / phone / card / SSN / Aadhaar / secret) with PERSON /
  contextual financial explicitly reported *unavailable*. A name + salary in
  prose **is missed** offline (blind-set miss `bpii01`) — the regex fallback is
  not entity recognition and we don't pretend it is.
- **Proportional action** — `data_policy.pii_action` per data class:
  `confidential` / `restricted` → **BLOCK**; `internal` / `public` →
  **MODIFY** (deterministic `[REDACTED_<TYPE>]`). Secrets / unsafe content
  always BLOCK. (Scenarios C vs C2 show both.)
- **Unsafe content / secrets / confidential-marking leak / forbidden entities** —
  deterministic patterns.
- **Bias** — a lightweight explicit-generalization signal (Tier 1) plus a
  **modular counterfactual probe** (Tier 2, rarely on the normal path). Honest
  that single-output bias detection is limited; borderline / proxy bias is a
  known blind-set gap.

Dimensions **overlap**: one response can be both a performance and a
responsibility finding; the final action comes from the combined policy.

**Privacy of the checker itself:** with `CONTROLPLANE_STORE_RAW=false` (default),
persisted trace/decision records store **redacted** request/response text;
detected entity **types/counts** are kept for audit. Live API responses to the
immediate caller are unaffected.

## 10. Feedback learning loop

```
production trace → user feedback (raw) → review queue → human/authoritative validation
   → trusted evidence → failure-pattern / baseline update → future routing changes
```

Trust tiers: `raw_feedback → machine_evidence → human_validated → authoritative`.
Guards against poisoning: raw feedback **cannot** promote a trusted pattern
alone; de-duplication; minimum evidence count; a confirmed **false positive
cools a pattern down**. Improves the **checker**, never retrains the LLM.

**Measured payoff (simulation):** once a pattern is trusted, matching
interactions are acted on without re-running Tier 2 → deep-check rate
**~6.4% → ~3.9%** while recall **~0.93 → ~1.00** (`_learning_effect` injects the
trusted patterns rather than running the full DB feedback flow — labelled a
simulation). The dashboard's learning-effect tiles can show run- or
configuration-specific simulation numbers; the README reports the documented
benchmark configuration (3,000 traces, seed 1729).

## 11. Agent / multi-turn support

Traces are step trees (`llm_call`, `retrieval`, `tool_call`, `final_response`).
**Risk inheritance is genuinely implemented** (`controlplane/sessions.py` +
`risk_engine`): after each turn, unresolved risk is threaded forward into the
next turn's `metadata["inherited_risk"]` **and** its terminal step. Resolution
semantics: `ALLOW/MONITOR/VERIFY` carry risk forward; `SAFE_FALLBACK` *softens
but does not erase* it; `BLOCK/STOP/HUMAN_REVIEW/MODIFY` resolve it. A later
`consequential_action` + inherited risk → `HUMAN_REVIEW`, with the reason string
citing *"compounding risk from earlier steps"*.

**Scenario G (verified):** turn 1 follows one of two conflicting SLA versions →
`conflicting_evidence` → **MONITOR** (unresolved); turn 2 inherits the unresolved
risk (~0.5) → **MONITOR**; turn 3 (irreversible transfer, no context of its own)
carries that inherited risk into a `consequential_action` → **HUMAN_REVIEW**, with
the reason string citing *"compounding risk from earlier steps"*. The
`inherited_risk_trace` is **non-decreasing** across the turns (e.g.
`[0.0, 0.5, 0.5]`); unresolved risk is carried forward into later turns and the
final gate fires on the consequential step. No scenario-name branching anywhere.

## 12. Latency strategy

> The claim is **proportional oversight**, not "parallelism makes it faster".

- Independent cheap checks are **dispatched together** (`asyncio.gather`). This is
  a dispatch/scheduling convenience, **not** guaranteed CPU parallelism: the 7
  Tier-1 checks are deterministic CPU work and complete sub-millisecond in the
  local prototype, and threading them was measured and is *slower* (task overhead
  > the work). Concurrency genuinely matters at Tier 2, where an evaluator may do
  real I/O.
- Deep evaluation is **not on the critical path** for normal low-risk requests
  (~6% deep-eval rate, measured).
- **Synchronous** handling for high-confidence PII / unsafe / high-impact / cost
  runaway — ControlPlane acts before the response reaches the user.
- **Asynchronous** deep evaluation for non-critical cases.
- Machine-local and run-dependent (this machine, mock evaluators — **not
  portable**): ControlPlane p95 overhead was measured in the low-millisecond
  range, while always-deep was materially higher in the same local benchmark. The
  portable claim is that deep evaluation is paid on ~6% rather than 100% of
  benchmark traffic — i.e. with a deep path costing X ms, expected added latency
  ≈ `0.06·X` (ControlPlane) vs `1.0·X` (always-deep). See
  [`docs/evaluation.md`](docs/evaluation.md).

## 13. Governance model

Versioned policy YAML per workflow (`config/policies`, `config/workflows`):
thresholds, routing knobs, human-review rules, data policy, latency/cost budgets.
**Editing a policy creates a new version; a trace preserves the version it ran
under.** Every `DecisionRecord` stamps `policy_name` + `policy_version`. Nothing
about the decision is hard-coded across the codebase.

## 14. Technology choices

Backend: **Python 3.11+, FastAPI, Pydantic v2, SQLModel + SQLite, asyncio,
scikit-learn, pytest**. Optional: Presidio, an OpenAI-compatible judge.
Frontend: **React + TypeScript + Vite + Recharts**. Deployment: **Docker
Compose** (one command) or plain local dev. No Kubernetes, Kafka, Redis, cloud
dependency or mandatory paid API — this is a competition prototype, and the
architecture is kept clean enough to scale *conceptually* without that infra.

## 15. Demo

`docs/demo.md` is a 5–7 minute script. **Demo mode** on the Overview page runs
scenarios live through the real engine (no hard-coded outcomes):

| | Scenario | Result (verified) |
| --- | --- | --- |
| A | Safe fast path | `ALLOW`, Tier 1, sub-ms overhead |
| B | Confidently wrong (60 vs 30 days) | `MODIFY` via trusted-source reconstruction |
| C | PII leak, `confidential` class | `BLOCK` (data-class policy) |
| C2 | Same leak, `internal` class | `MODIFY` — deterministic `[REDACTED_*]` |
| D | No ground truth (market forecast) | `HUMAN_REVIEW`, confidence 0.35, label stays `no_ground_truth` |
| E | Cost runaway (in-flight agent) | `STOP_EXECUTION`, projected-spend simulation |
| F | Bias signal | `BLOCK` |
| G | Multi-turn compounding risk | `inherited_risk_trace` non-decreasing (e.g. `[0.0, 0.5, 0.5]`) → final `HUMAN_REVIEW` citing compounding risk |

**Show live:** B, E, G, Feedback→Learning. Reference the rest on the dashboard.

## 16. Evaluation methodology

Two suites, reported **separately** (`scripts/run_evaluation.py --suite both`):

- **Regression suite** — 186 deterministic cases, **co-designed with the
  detectors**. A controlled self-consistency / regression suite. Near-perfect
  scores on the injected dimensions are expected *by construction* and are **not**
  evidence of generalisation. The one independent signal is the false-positive
  rate on the 62 clean-normal cases.
- **Blind challenge set** — ~43 independently authored cases (paraphrased
  contradictions, contextual PII, borderline bias, adversarial phrasing,
  conflicting evidence, hard negatives…). **Not** a formal unbiased benchmark;
  `predicted_outcome` frozen; detectors not tuned against it; **misses reported**.
- **Three-arm benchmark** (`scripts/benchmark.py`) split into **structural**
  (deterministic), **runtime-local** (this machine), **simulated-cost**
  (synthetic model) tiers. North star: *risk coverage per unit of overhead*.

Full detail + the blind misses: `docs/evaluation.md`.

## 17. Results

### Regression suite (controlled — near-perfect by construction)

| Dimension | Precision | Recall | FPR | FNR |
| --- | --- | --- | --- | --- |
| Performance | 1.00 | 0.96 | 0.00 | 0.04 |
| Cost | 1.00 | 1.00 | 0.00 | 0.00 |
| Responsibility | 1.00 | 1.00 | 0.00 | 0.00 |

clean-normal false-positive rate **0.00** · correct-intervention **0.98** ·
missed high-risk **2** · expected-action match **0.91** · no-ground-truth
labelled correctly **100%**, confidence-lowered **100%**, asserted-false **0%**.

### Blind challenge set (the honest, harder number)

- overall **action-in-expected-range: ~0.63**
- **hard-negative false-positive rate: ~0.12**
- per-dimension recall (unambiguous cases): performance ~0.38, responsibility
  ~0.43, cost 1.0
- calibration: `expect_catch` handled **~88%**; `expect_miss` **0%** (missed all,
  as predicted)
- **reported misses:** verbal/paraphrased contradictions; contextual PII (name +
  salary) without Presidio; conflicting small unitless quantities; one
  structured-fact false positive. See `docs/evaluation.md`.

### Three-arm benchmark — structural tier (deterministic, 3,000 traces, seed 1729)

| | A: no checker | B: always deep | C: ControlPlane |
| --- | --- | --- | --- |
| recall | 0.00 | 0.93 | **0.93** |
| precision | 0.00 | 0.86 | **0.86** |
| false-positive rate | 0.00 | 0.02 | **0.02** |
| fast-path % | 100% | 0% | **93.7%** |
| deep-eval % | 0% | 100% | **6.3%** |

→ **ControlPlane matched always-deep recall: 0.93 vs 0.93** (equal detection
coverage in this benchmark, not 100% absolute recall), **FPR delta: 0.00**,
no-ground-truth handling: confidence-lowered 100% / high-impact-escalated 100%.
**Runtime** (machine-local, run-dependent): ControlPlane p95 overhead was in the
low-millisecond range and always-deep was materially higher in the same local
benchmark; the portable claim is that deep evaluation is paid on ~6% rather than
100% of benchmark traffic.
**Simulated cost:** ~0.84 checker-work reduction (an artifact of the assigned
`cost_units`; direction defensible, not a dollar figure).
**Learning effect (simulation):** deep-check rate ~6.4% → ~3.9%, recall ~0.93 →
~1.00 — labelled a simulation (`_learning_effect` injects trusted patterns rather
than running the full DB feedback flow).

**Dashboard note:** the Performance Benchmark page lets you choose the trace
count, so the structural, runtime, cost and learning-effect numbers shown in the
dashboard may vary by the run you select. The README headline results above use
the fixed **3,000-trace benchmark with seed 1729**.

**Safe claim:** *ControlPlane reduces unnecessary deep verification while
retaining comparable detection coverage in this controlled benchmark.* Arm A's
recall 0 is definitional (a no-op). No universal-latency or production-dollar
claim is made.

## 18. Limitations

Structured-fact + lexical grounding, not semantic fact-checking (verbal
contradictions missed); regex PII fallback is **not** entity recognition
(contextual name+salary missed offline); bias detection from single outputs is
weak; conflicting-evidence check is conservative (small unitless quantities
missed); LLM-judge can be wrong (and is capped under no-ground-truth); robust
baselines need data; regression suite ≠ external benchmark; blind set ≠ formal
unbiased benchmark; synthetic cost ≠ production dollars; local latency ≠
universal latency; risk scores are **interpretable decision scores, not
calibrated probabilities**; SQLite / single-process is prototype scope; raw
content storage is opt-in; **not** a replacement for IAM / auth / data
governance / compliance. Full list: `docs/limitations.md`.

## 19. Future roadmap

- Real OTLP export; adapters for Langfuse / NeMo Guardrails / Ragas / DeepEval.
- Optional Tier-2 semantic contradiction check for verbally-phrased errors.
- Speculative safe pre-checks concurrent with generation (policy-gated).
- Embedding-based grounding; Presidio recognisers wired in; a real counterfactual
  fairness harness with proper datasets.
- Configurable data retention & field-level capture; RBAC on the dashboard.
- Horizontal scale-out (stateless workers + Postgres); per-tenant policy stores.
- Richer interaction signatures; wire `GoldenCaseRow` into a quality-baseline evaluator.

## 20. How to run

**No proprietary API keys required. `LLM_PROVIDER=mock` is the default.**

### Docker (one command)

```bash
# .env is OPTIONAL — Docker runs with working defaults and no .env file.
# To customise, copy the example first:
#   macOS/Linux:         cp .env.example .env
#   Windows PowerShell:  Copy-Item .env.example .env
docker compose up --build
# backend  → http://localhost:8000  (API docs at /docs)
# dashboard → http://localhost:5173
# On first boot the backend seeds 1,200 synthetic demo traces (demo data only).
```

### Local development

> The `make` targets assume **GNU Make**. On Windows the Docker path above is the
> recommended option unless Make is installed.

```bash
# 1. install requirements
make setup                    # creates backend/.venv, installs backend + frontend deps
#    (optional extras: backend/.venv/Scripts/pip install -r backend/requirements-optional.txt)

# 2. start backend            → http://localhost:8000
make dev-backend

# 3. start frontend           → http://localhost:5173
make dev-frontend             # (or `make dev` to run both)

# 4. seed demo data (demo-data volume only, not a system limit or performance figure)
make seed                     # generates synthetic demo data (default 5,000 traces) + scenarios A–G + feedback/validation
#   change the amount with: backend/.venv/Scripts/python scripts/seed_demo.py --count 1200

# 5. open dashboard
#    http://localhost:5173

# 6. run a demo scenario
#    Overview page → "Demo mode" bar → click A–G
```

### Reproduce the numbers

Run these from the **repository root** (the interpreter is the project venv;
on macOS/Linux use `backend/.venv/bin/python` instead of
`backend/.venv/Scripts/python`):

```bash
make test                                                             # 69 tests: unit + integration + evaluation
backend/.venv/Scripts/python scripts/run_evaluation.py --suite both   # -> results/evaluation_report.{json,md}
backend/.venv/Scripts/python scripts/benchmark.py --count 3000        # -> results/benchmark_report.{json,md}
backend/.venv/Scripts/python scripts/benchmark.py --count 3000 --deep-eval-sim-latency 300
```

### Minimal integration (SDK)

> The SDK facade (`app/sdk/client.py`) is an **illustrative integration surface**
> — the running system uses the same `controlplane.pipeline` functions directly.

```python
from app.sdk.client import controlplane

trace = controlplane.observe(
    workflow="customer_support",
    request=user_query,
    response=ai_response,
    retrieved_context=chunks,
    authoritative_facts={"return_window_days": {"value": 30, "unit": "days",
                                                "keywords": ["return", "refund"],
                                                "statement": "Returns are accepted within 30 days of delivery."}},
)
decision = await controlplane.evaluate(trace)
return decision.safe_response          # ALLOW → original; MODIFY → redacted/reconstructed; BLOCK → safe notice

# agents: gate each step in-flight
gate = await controlplane.check_step(partial_trace)
if gate.directive == "STOP":
    ...
```

---

### Positioning

**Adaptive Runtime AI Oversight** — broader than any single detector, narrower
than enterprise-wide governance. Not an AI safety filter, governance dashboard,
hallucination detector, AI firewall, or AI judge.

> As AI scales, oversight does not have to scale linearly with AI traffic or
> compute. **ControlPlane makes AI oversight adaptive.**

