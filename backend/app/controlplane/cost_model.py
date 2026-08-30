"""Deterministic cost estimation.

Cost is the most deterministic risk dimension — no LLM is used to estimate it.
Prices are illustrative prototype values (USD per 1K tokens) and are trivially
editable. Tool calls carry a small fixed compute cost.
"""
from __future__ import annotations

from app.core.schemas import AITrace, StepType, TraceStep

# USD per 1,000 tokens (input, output). Illustrative prototype values.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "mock-model": (0.0005, 0.0015),
    "mock-model-mini": (0.00015, 0.0006),
    "mock-model-pro": (0.003, 0.009),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "claude-sonnet": (0.003, 0.015),
    "claude-haiku": (0.0008, 0.004),
    "llama-3-70b": (0.0006, 0.0008),
    "mistral-large": (0.002, 0.006),
}
_DEFAULT_PRICE = (0.001, 0.002)
TOOL_CALL_COST = 0.0004          # fixed compute/egress cost per tool call
RETRIEVAL_COST = 0.0002         # vector search + embedding cost per retrieval


def price_for(model: str | None) -> tuple[float, float]:
    if not model:
        return _DEFAULT_PRICE
    return MODEL_PRICES.get(model, _DEFAULT_PRICE)


def step_cost(step: TraceStep) -> float:
    """Cost of a single execution step."""
    if step.cost_usd:
        return step.cost_usd
    if step.type == StepType.TOOL_CALL:
        return TOOL_CALL_COST * (1 + step.retries)
    if step.type == StepType.RETRIEVAL:
        return RETRIEVAL_COST * (1 + step.retries)
    in_price, out_price = price_for(step.model)
    cost = (step.usage.input_tokens / 1000.0) * in_price
    cost += (step.usage.output_tokens / 1000.0) * out_price
    return round(cost * (1 + step.retries), 6)


def estimate_trace_cost(trace: AITrace) -> float:
    """Total estimated cost for a (possibly partial) trace."""
    if trace.steps:
        return round(sum(step_cost(s) for s in trace.steps), 6)
    in_price, out_price = price_for(trace.model)
    cost = (trace.total_input_tokens / 1000.0) * in_price
    cost += (trace.total_output_tokens / 1000.0) * out_price
    return round(cost, 6)


def project_final_cost(trace: AITrace, expected_cost: float | None = None) -> tuple[float, str]:
    """Estimate the final cost of an IN-FLIGHT agent trace from its trajectory.

    Returns (projected_cost, trajectory_label).

    Method (interpretable, no ML): look at the per-step cost deltas of the last
    few steps. If cost is accelerating (each step costs more than the previous),
    extrapolate the growth for the number of steps we'd still expect; otherwise
    assume roughly linear continuation toward the expected step budget.
    """
    steps = [s for s in trace.steps if s.type != StepType.FINAL_RESPONSE]
    if not steps:
        return estimate_trace_cost(trace), "flat"

    cumulative = 0.0
    per_step: list[float] = []
    for s in steps:
        c = step_cost(s)
        cumulative += c
        per_step.append(c)

    if not trace.in_flight:
        return round(cumulative, 6), "complete"

    recent = per_step[-3:]
    avg_recent = sum(recent) / len(recent)
    growth = 1.0
    if len(recent) >= 2 and recent[0] > 0:
        growth = recent[-1] / recent[0]

    # How many more steps do we expect? Use the expected cost to bound it, else 4.
    remaining_steps = 4
    if expected_cost and avg_recent > 0:
        remaining_steps = max(2, min(12, int((expected_cost * 3 - cumulative) / avg_recent) + 3))

    if growth > 1.15:  # accelerating — geometric extrapolation
        projected = cumulative
        step_c = recent[-1]
        for _ in range(remaining_steps):
            step_c *= min(growth, 1.8)
            projected += step_c
        label = "rapidly_increasing"
    else:              # steady — linear continuation
        projected = cumulative + avg_recent * remaining_steps
        label = "steady"

    return round(projected, 6), label
