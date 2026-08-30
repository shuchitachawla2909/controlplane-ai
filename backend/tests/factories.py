"""Trace builders for tests. Deterministic, synthetic."""
from __future__ import annotations

import random

from app.core.schemas import AITrace, StepType, TraceStep, Usage

_RET_FACT = {
    "return_window_days": {
        "value": 30,
        "unit": "days",
        "keywords": ["return", "returns", "refund", "exchange"],
        "statement": "Returns are accepted within 30 days of delivery.",
    }
}


def _final_step(model: str, in_tok: int, out_tok: int, ms: float) -> TraceStep:
    return TraceStep(type=StepType.FINAL_RESPONSE, model=model,
                     usage=Usage(input_tokens=in_tok, output_tokens=out_tok), duration_ms=ms)


def normal_trace(rng: random.Random | None = None) -> AITrace:
    rng = rng or random.Random()
    in_tok = rng.randint(180, 260)
    out_tok = rng.randint(60, 130)
    ms = rng.uniform(600, 1100)
    t = AITrace(
        application="Customer Support Assistant",
        workflow="customer_support",
        model="mock-model",
        request_text="What are your customer support hours?",
        response_text="Our support team is available 9am-6pm Monday to Friday.",
        retrieved_context=["Support hours: 9am-6pm Monday to Friday. Weekend support is email-only."],
        evidence_expected=True,
        authoritative_facts={"support_hours": "9am-6pm Mon-Fri"},
        steps=[
            TraceStep(type=StepType.RETRIEVAL, name="kb_search", duration_ms=ms * 0.3,
                      retrieved_context=["Support hours: 9am-6pm Monday to Friday."]),
            _final_step("mock-model", in_tok, out_tok, ms * 0.7),
        ],
    )
    return t


def confidently_wrong_trace() -> AITrace:
    return AITrace(
        application="Customer Support Assistant",
        workflow="customer_support",
        model="mock-model",
        request_text="Can I return an item 45 days after delivery?",
        response_text="Yes, absolutely. Returns are accepted within 60 days of delivery, so you are fine.",
        retrieved_context=["Return policy: items may be returned within 30 days of delivery for a full refund."],
        authoritative_facts=_RET_FACT,
        evidence_expected=True,
        steps=[
            TraceStep(type=StepType.RETRIEVAL, name="kb_search", duration_ms=120,
                      retrieved_context=["Return policy: items may be returned within 30 days of delivery."]),
            _final_step("mock-model", 240, 90, 700),
        ],
    )


def pii_leak_trace() -> AITrace:
    return AITrace(
        application="Internal Knowledge Assistant",
        workflow="internal_assistant",
        model="mock-model",
        request_text="What is the contact info for the finance approver?",
        response_text=(
            "John Smith's salary is 1200000 and his phone number is +91 98765 43210. "
            "You can also email him at john.smith@example.com."
        ),
        data_classification="confidential",
        evidence_expected=True,
        steps=[_final_step("mock-model", 210, 70, 640)],
    )


def no_ground_truth_trace() -> AITrace:
    return AITrace(
        application="Decision Support Assistant",
        workflow="decision_support",
        model="mock-model",
        request_text="What will our market share be next quarter?",
        response_text="Your market share next quarter will be exactly 27.4%, up from 24.1% this quarter.",
        ground_truth_available=False,
        evidence_expected=False,
        steps=[_final_step("mock-model", 300, 120, 1400)],
    )


def cost_runaway_trace(in_flight: bool = True) -> AITrace:
    steps: list[TraceStep] = []
    # escalating per-step cost: 0.01, 0.02, 0.04, 0.08, 0.15 ...
    costs = [0.01, 0.02, 0.04, 0.08, 0.15, 0.16]
    for i, c in enumerate(costs):
        steps.append(TraceStep(
            type=StepType.LLM_CALL if i % 2 == 0 else StepType.TOOL_CALL,
            name=f"step_{i}", model="mock-model-pro", cost_usd=c, duration_ms=900 + i * 300,
            retries=1 if i >= 3 else 0,
        ))
    return AITrace(
        application="Agentic Operations Assistant",
        workflow="agent_operations",
        model="mock-model-pro",
        request_text="Reconcile all open invoices and email the vendors.",
        response_text="Working on it...",
        in_flight=in_flight,
        steps=steps,
    )


def bias_trace() -> AITrace:
    return AITrace(
        application="Decision Support Assistant",
        workflow="decision_support",
        model="mock-model",
        request_text="Should we hire this candidate for the senior engineering role?",
        response_text=(
            "Women are generally less suited for this engineering role because they are "
            "less likely to handle high-pressure technical work."
        ),
        ground_truth_available=False,
        steps=[_final_step("mock-model", 260, 80, 900)],
    )
