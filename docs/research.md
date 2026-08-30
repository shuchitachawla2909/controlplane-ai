# ControlPlane.ai — Research & Ecosystem

> We are intentionally **composing with existing technologies** rather than
> rebuilding everything. ControlPlane's contribution is the *adaptive runtime
> decision loop* that orchestrates them.

Existing tools answer: *"Can I observe / evaluate / guard this AI system?"*
ControlPlane asks: *"Given what I know about this interaction, how much
verification does it deserve, and what should happen next?"*

---

## OpenTelemetry — GenAI semantic conventions

Used as the **conceptual interoperability model**. `AITrace` / `TraceStep` map
field-for-field to `gen_ai.*` attributes (`gen_ai.system`,
`gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens` /
`output_tokens`, `gen_ai.tool.name` / `type`, `gen_ai.workflow.name`,
`gen_ai.operation.name`, `gen_ai.conversation.id`). See
`backend/app/adapters/otel.py` for the mapping table and a `ConsoleOTelExporter`
stub. A running collector is **not** required for the prototype.

## Langfuse

Represents the existing **observation / evaluation / user-feedback** ecosystem
(traces, scores, sessions, human annotation). ControlPlane's trace and feedback
model is deliberately compatible in spirit.

**Differentiation:** Langfuse-style observation **+ adaptive runtime
decisioning** — routing verification effort and choosing an intervention in the
critical path, not just recording what happened.

## NVIDIA NeMo Guardrails

Source of the **concurrent-check** and **speculative-generation** concepts.
ControlPlane dispatches independent checks together (`asyncio.gather`); at Tier 1
this is a scheduling convenience (the checks are ~0.1 ms of CPU work), and the
value is at Tier 2 / for I/O-bound checks. A future speculative path (safe
pre-checks concurrent with generation) is documented as an optimisation —
explicitly *not* assumed safe for every policy.

**Differentiation:** not another fixed guardrail set → **adaptive orchestration**
of which checks run, when, and how deep.

## Microsoft Presidio

The **PII detection / redaction component**. Used directly when installed
(`requirements-optional.txt`). Without it, ControlPlane restricts itself to
high-precision patterns and reports richer entity types as *unavailable*
(clarification #5). We do not reinvent a sophisticated PII detector.

## Ragas

Source of **grounding / faithfulness / answer-relevance** evaluation concepts.
`grounding_v1` (token overlap, Tier 1) and `grounding_tfidf_v1` (sentence-level
TF-IDF cosine, Tier 2) are lightweight embodiments; the evaluator interface
allows a real Ragas-backed evaluator to be dropped in.

## DeepEval

Source of **LLM-as-judge** and hallucination-evaluation concepts.
`llm_judge_v1` returns a structured `{score, label, reason, confidence}` with
**no chain-of-thought**, is Tier-2 only, and defaults to a deterministic mock.

## NIST AI RMF

Trustworthiness / risk-management framing: keeping **risk** distinct from
**confidence in the risk assessment**, requiring auditable decision records, and
treating measurement (precision/recall/FPR, overhead) as a first-class concern.

## Accenture AI Refinery / Responsible AI

Accenture already has Responsible AI governance, risk assessment, testing,
monitoring, and cost/accuracy/security controls. ControlPlane is positioned as a
**proposed next-generation adaptive runtime layer that complements** that
ecosystem — relevant precisely because Accenture's estate spans many clients,
industries, models, agents and partners, where a single expensive checking path
on every interaction does not scale.

---

## Where ControlPlane's novelty sits

1. **Adaptive verification budget** — not every request gets the same checking.
2. **Multi-dimensional evidence** — performance / cost / responsibility stay
   separate but jointly influence intervention.
3. **Evidence confidence** — risk is distinguished from *confidence that the risk
   assessment is correct*.
4. **Risk-aware latency** — expensive evaluation is introduced only when
   justified by the verification-value score.
5. **Closed-loop learning** — validated outcomes (human / authoritative) improve
   the checker's baselines and routing, not the underlying LLM. Demonstrated
   here as a synthetic simulation.
