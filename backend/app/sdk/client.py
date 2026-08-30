"""Minimal integration surface (§57).

How a hypothetical AI application would use ControlPlane:

    from app.sdk.client import controlplane

    trace = controlplane.observe(
        workflow="customer_support",
        model="mock-model",
        request=user_query,
        response=ai_response,
        retrieved_context=chunks,
        authoritative_facts={"return_window_days": {"value": 30, "unit": "days",
                                                    "keywords": ["return", "refund"]}},
    )
    decision = await controlplane.evaluate(trace)
    return decision.safe_response

For agents, feed steps as they happen and gate on the in-flight hook:

    async for step in agent.run():
        trace.steps.append(step)
        gate = await controlplane.check_step(trace)
        if gate.directive == "STOP":
            break
"""
from __future__ import annotations

from typing import Any

from app.controlplane.baselines import BaselineProvider
from app.controlplane.pipeline import evaluate_trace
from app.controlplane.router import LearningContext, StepDecision, check_agent_step
from app.core.schemas import AITrace, DecisionRecord, StepType, TraceStep, Usage


class ControlPlane:
    """Stateless facade. Persistence/learning live in ``controlplane.pipeline``."""

    def observe(
        self,
        *,
        workflow: str,
        request: str,
        response: str = "",
        application: str | None = None,
        model: str = "mock-model",
        provider: str = "mock",
        profile: str | None = None,
        session_id: str | None = None,
        retrieved_context: list[str] | None = None,
        authoritative_facts: dict[str, Any] | None = None,
        ground_truth_available: bool = True,
        evidence_expected: bool = False,
        data_classification: str | None = None,
        steps: list[TraceStep] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        turn_index: int = 0,
        in_flight: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> AITrace:
        trace = AITrace(
            application=application or workflow.replace("_", " ").title(),
            workflow=workflow,
            profile=profile or workflow,
            model=model,
            provider=provider,
            request_text=request,
            response_text=response,
            retrieved_context=retrieved_context or [],
            authoritative_facts=authoritative_facts or {},
            ground_truth_available=ground_truth_available,
            evidence_expected=evidence_expected,
            data_classification=data_classification,
            steps=steps or [],
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            turn_index=turn_index,
            in_flight=in_flight,
            metadata=metadata or {},
        )
        if session_id:
            trace.session_id = session_id
        if not trace.steps and response:
            trace.new_step(
                type=StepType.FINAL_RESPONSE,
                model=model,
                provider=provider,
                usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                duration_ms=float(metadata.get("latency_ms", 0.0)) if metadata else 0.0,
            )
        return trace

    async def evaluate(
        self,
        trace: AITrace,
        *,
        learning: LearningContext | None = None,
        baselines: BaselineProvider | None = None,
        enable_llm_judge: bool = True,
    ) -> DecisionRecord:
        result = await evaluate_trace(
            trace, learning=learning, baselines=baselines, enable_llm_judge=enable_llm_judge
        )
        return result.record

    async def check_step(
        self,
        partial_trace: AITrace,
        *,
        baselines: BaselineProvider | None = None,
    ) -> StepDecision:
        return await check_agent_step(partial_trace, baselines=baselines)


controlplane = ControlPlane()
