"""OpenTelemetry GenAI compatibility (§32, §51).

ControlPlane's internal schema is deliberately close to the OpenTelemetry
GenAI semantic conventions, but the prototype does NOT require a running
collector. This module documents the mapping and provides:

* ``trace_to_otel_spans`` — convert an :class:`AITrace` into span-like dicts
  using ``gen_ai.*`` attribute keys.
* ``ConsoleOTelExporter`` — a stub exporter (prints / collects) that a real
  OTLP exporter could replace with no change to the rest of the system.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.schemas import AITrace, StepType, TraceStep

# ControlPlane field  ->  OpenTelemetry GenAI attribute
FIELD_MAP: dict[str, str] = {
    "provider": "gen_ai.system",
    "model": "gen_ai.request.model",
    "response_model": "gen_ai.response.model",
    "input_tokens": "gen_ai.usage.input_tokens",
    "output_tokens": "gen_ai.usage.output_tokens",
    "tool_name": "gen_ai.tool.name",
    "tool_type": "gen_ai.tool.type",
    "workflow": "gen_ai.workflow.name",
    "operation": "gen_ai.operation.name",
    "conversation_id": "gen_ai.conversation.id",
}

_OP = {
    StepType.LLM_CALL: "chat",
    StepType.RETRIEVAL: "retrieve",
    StepType.TOOL_CALL: "execute_tool",
    StepType.FINAL_RESPONSE: "chat",
}


def step_to_span(trace: AITrace, step: TraceStep) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "gen_ai.system": step.provider or trace.provider,
        "gen_ai.operation.name": _OP[step.type],
        "gen_ai.workflow.name": trace.workflow,
        "gen_ai.conversation.id": trace.session_id,
        "gen_ai.usage.input_tokens": step.usage.input_tokens,
        "gen_ai.usage.output_tokens": step.usage.output_tokens,
        "controlplane.step.type": step.type.value,
        "controlplane.step.cost_usd": step.cost_usd,
        "controlplane.step.cumulative_cost_usd": step.cumulative_cost_usd,
        "controlplane.step.retries": step.retries,
    }
    if step.model or trace.model:
        attrs["gen_ai.request.model"] = step.model or trace.model
    if step.tool_name:
        attrs["gen_ai.tool.name"] = step.tool_name
        attrs["gen_ai.tool.type"] = step.tool_type or "function"
    return {
        "name": f"{_OP[step.type]} {step.name or step.type.value}",
        "trace_id": trace.trace_id,
        "span_id": step.step_id,
        "parent_span_id": step.parent_id,
        "start_time": step.started_at,
        "duration_ms": step.duration_ms,
        "attributes": attrs,
    }


def trace_to_otel_spans(trace: AITrace) -> list[dict[str, Any]]:
    root = {
        "name": f"controlplane.trace {trace.workflow}",
        "trace_id": trace.trace_id,
        "span_id": trace.request_id,
        "parent_span_id": None,
        "start_time": trace.created_at,
        "duration_ms": trace.latency_ms,
        "attributes": {
            "gen_ai.system": trace.provider,
            "gen_ai.request.model": trace.model,
            "gen_ai.workflow.name": trace.workflow,
            "gen_ai.conversation.id": trace.session_id,
            "gen_ai.usage.input_tokens": trace.total_input_tokens,
            "gen_ai.usage.output_tokens": trace.total_output_tokens,
            "controlplane.estimated_cost_usd": trace.estimated_cost_usd,
            "controlplane.ground_truth_available": trace.ground_truth_available,
        },
    }
    return [root, *(step_to_span(trace, s) for s in trace.steps)]


@dataclass
class ConsoleOTelExporter:
    """Stub. A real deployment swaps this for an OTLP/gRPC exporter."""

    collected: list[dict[str, Any]] = field(default_factory=list)
    echo: bool = False

    def export(self, trace: AITrace) -> list[dict[str, Any]]:
        spans = trace_to_otel_spans(trace)
        self.collected.extend(spans)
        if self.echo:
            for s in spans:
                print(json.dumps(s, default=str))
        return spans


default_exporter = ConsoleOTelExporter()
