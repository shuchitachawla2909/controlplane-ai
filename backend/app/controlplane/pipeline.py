"""End-to-end orchestration with persistence.

    ingest -> Tier 0 -> parallel Tier 1 -> risk engine -> policy -> routing
      -> [Tier 2] -> decision -> intervention -> audit record -> DB
      -> baseline update (anomalies quarantined) -> review queue (if needed)

``evaluate_trace`` is the pure, DB-free core used by tests and the benchmark.
``ingest_and_evaluate`` adds persistence and the learning loop.
"""
from __future__ import annotations

from sqlmodel import Session

from app.controlplane.baselines import BaselineProvider
from app.controlplane.learning import enqueue_review, load_learning_context
from app.controlplane.router import LearningContext, PipelineResult, run_pipeline
from app.core.config import get_settings
from app.core.models import DecisionRow, TraceRow
from app.core.schemas import AITrace, DecisionRecord
from app.controlplane.observer import redact_text, to_row_previews

_COST_METRICS = {"cost_usd", "model_calls", "tool_calls", "retries", "latency_ms", "total_tokens"}


def _redact_trace_json(trace: AITrace) -> dict:
    """Full trace dump with sensitive free-text masked (detection evidence and
    telemetry are untouched). Skipped entirely when CONTROLPLANE_STORE_RAW=true.
    """
    data = trace.model_dump(mode="json")
    if get_settings().store_raw:
        return data
    data["request_text"] = redact_text(data.get("request_text", ""))
    data["response_text"] = redact_text(data.get("response_text", ""))
    for step in data.get("steps", []):
        for key in ("input_meta", "output_meta"):
            meta = step.get(key)
            if isinstance(meta, dict):
                step[key] = {
                    k: (redact_text(v) if isinstance(v, str) else v) for k, v in meta.items()
                }
        step["retrieved_context"] = [redact_text(c) for c in step.get("retrieved_context", [])]
    data["retrieved_context"] = [redact_text(c) for c in data.get("retrieved_context", [])]
    return data


async def evaluate_trace(
    trace: AITrace,
    *,
    learning: LearningContext | None = None,
    baselines: BaselineProvider | None = None,
    enable_llm_judge: bool = True,
    force_deep: bool = False,
) -> PipelineResult:
    return await run_pipeline(
        trace,
        learning=learning,
        baselines=baselines,
        enable_llm_judge=enable_llm_judge,
        force_deep=force_deep,
    )


def _trace_row(trace: AITrace) -> TraceRow:
    req_prev, resp_prev = to_row_previews(trace)
    redacted = _redact_trace_json(trace)
    return TraceRow(
        trace_id=trace.trace_id,
        session_id=trace.session_id,
        request_id=trace.request_id,
        application=trace.application,
        workflow=trace.workflow,
        model=trace.model,
        provider=trace.provider,
        created_at=trace.created_at,
        turn_index=trace.turn_index,
        in_flight=trace.in_flight,
        request_preview=req_prev,
        response_preview=resp_prev,
        latency_ms=trace.latency_ms,
        model_calls=trace.model_calls,
        tool_calls=trace.tool_calls,
        retrieval_events=trace.retrieval_events,
        retries=trace.retries,
        input_tokens=trace.total_input_tokens,
        output_tokens=trace.total_output_tokens,
        estimated_cost_usd=trace.estimated_cost_usd,
        ground_truth_available=trace.ground_truth_available,
        steps=redacted.get("steps", []),
        trace_json=redacted,
    )


def _redact_record(rec: DecisionRecord) -> dict:
    """Persisted decision record with sensitive free-text masked. `redact_text`
    only touches high-precision patterns (email / phone / card / secret /
    "Name Name's"), so evaluator names, labels and numbers are untouched.
    """
    data = rec.model_dump(mode="json")
    if get_settings().store_raw:
        return data

    def scrub(obj):
        if isinstance(obj, str):
            return redact_text(obj)
        if isinstance(obj, list):
            return [scrub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: scrub(v) for k, v in obj.items()}
        return obj

    data = scrub(data)
    data["original_response_redacted"] = data.get("original_response", "") != rec.original_response
    return data


def _decision_row(rec: DecisionRecord) -> DecisionRow:
    persisted = _redact_record(rec)
    return DecisionRow(
        decision_id=rec.decision_id,
        trace_id=rec.trace_id,
        session_id=rec.session_id,
        application=rec.application,
        workflow=rec.workflow,
        created_at=rec.created_at,
        policy_name=rec.policy_name,
        policy_version=rec.policy_version,
        performance_risk=rec.performance_risk,
        cost_risk=rec.cost_risk,
        responsibility_risk=rec.responsibility_risk,
        performance_confidence=rec.performance_confidence,
        cost_confidence=rec.cost_confidence,
        responsibility_confidence=rec.responsibility_confidence,
        overall_risk=rec.overall_risk,
        evidence_confidence=rec.evidence_confidence,
        severity=rec.severity.value,
        impact=rec.impact.value,
        novelty=rec.novelty,
        action=rec.action.value,
        tier=max(rec.tiers_run) if rec.tiers_run else 1,
        tiers_run=rec.tiers_run,
        evaluators_run=rec.evaluators_run,
        verification_value=rec.verification_value,
        controlplane_overhead_ms=rec.controlplane_overhead_ms,
        sequential_check_ms=rec.sequential_check_ms,
        parallel_check_ms=rec.parallel_check_ms,
        synchronous=rec.synchronous,
        projected_cost_usd=rec.projected_cost_usd,
        cost_budget_usd=rec.cost_budget_usd,
        prevented_spend_usd=rec.prevented_spend_usd,
        execution_stopped=rec.execution_stopped,
        response_modified=rec.response_modified,
        modification_method=rec.modification_method,
        requires_human_review=rec.requires_human_review,
        record=persisted,
    )


def persist_result(session: Session, trace: AITrace, result: PipelineResult) -> DecisionRow:
    """Write the trace + decision (+ review case) rows for a completed evaluation."""
    session.add(_trace_row(trace))
    drow = _decision_row(result.record)
    session.add(drow)
    if result.record.requires_human_review:
        enqueue_review(session, drow, reason=result.record.why_action or "requires human review")
    return drow


async def ingest_and_evaluate(
    trace: AITrace,
    session: Session,
    *,
    persist: bool = True,
    update_baseline: bool = True,
    enable_llm_judge: bool = True,
) -> PipelineResult:
    learning = load_learning_context(session, trace.workflow)
    baselines = BaselineProvider(trace.workflow, session)

    result = await run_pipeline(trace, learning=learning, baselines=baselines, enable_llm_judge=enable_llm_judge)
    rec = result.record

    if persist:
        persist_result(session, trace, result)

    if update_baseline:
        anomalous: set[str] = set()
        if result.risk.cost.risk >= 0.6 or rec.execution_stopped:
            anomalous |= _COST_METRICS
        baselines.observe_trace(trace, anomalous)
        baselines.persist()

    return result
