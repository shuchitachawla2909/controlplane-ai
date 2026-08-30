"""Tier 0 — OBSERVE.

Every AI execution passes through Tier 0. It must be extremely cheap: it only
normalizes the trace, counts what already happened, and estimates cost. It
makes NO semantic model calls.

It also produces the redacted previews that are safe to persist / show in the
dashboard — the system that detects privacy leaks must not become one (§65).
"""
from __future__ import annotations

import re

from app.controlplane.cost_model import estimate_trace_cost, step_cost
from app.core.schemas import AITrace, StepType

_PREVIEW_LEN = 280

# Conservative, high-precision redaction for anything we persist or display.
_REDACT_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?\d[ -]?){9,14}\d(?!\d)"), "[PHONE]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),
    (re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9]{16,}\b"), "[SECRET]"),
    (re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+'s\b"), "[NAME]'s"),
]


def redact_text(text: str) -> str:
    """Redact high-precision sensitive patterns. No truncation."""
    out = text or ""
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_for_storage(text: str) -> str:
    """Redacted + truncated — for list/preview fields."""
    return redact_text(text)[:_PREVIEW_LEN]


def observe(trace: AITrace) -> AITrace:
    """Populate the derived Tier 0 fields on ``trace`` in place and return it."""
    trace.profile = trace.profile or trace.workflow

    in_tok = out_tok = model_calls = tool_calls = retrieval_events = retries = 0
    latency = 0.0
    cumulative = 0.0

    for step in sorted(trace.steps, key=lambda s: s.index):
        in_tok += step.usage.input_tokens
        out_tok += step.usage.output_tokens
        retries += step.retries
        latency += step.duration_ms
        cumulative += step_cost(step)
        step.cumulative_cost_usd = round(cumulative, 6)
        if step.type == StepType.LLM_CALL:
            model_calls += 1
        elif step.type == StepType.TOOL_CALL:
            tool_calls += 1
        elif step.type == StepType.RETRIEVAL:
            retrieval_events += 1
            if step.retrieved_context and not trace.retrieved_context:
                # surface retrieval chunks at trace level for grounding checks
                trace.retrieved_context = list(step.retrieved_context)

    # Fall back to trace-level counts when no explicit steps were supplied.
    trace.total_input_tokens = in_tok or trace.total_input_tokens
    trace.total_output_tokens = out_tok or trace.total_output_tokens
    trace.model_calls = model_calls or trace.model_calls or (1 if trace.response_text else 0)
    trace.tool_calls = tool_calls or trace.tool_calls
    trace.retrieval_events = retrieval_events or trace.retrieval_events
    trace.retries = retries or trace.retries
    trace.latency_ms = latency or trace.latency_ms
    trace.estimated_cost_usd = estimate_trace_cost(trace)
    return trace


def to_row_previews(trace: AITrace) -> tuple[str, str]:
    """Redacted request/response previews safe for the DB and dashboard."""
    return redact_for_storage(trace.request_text), redact_for_storage(trace.response_text)
