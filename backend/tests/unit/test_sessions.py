"""Session risk-inheritance semantics (§21, §22).

The conceptual distinction that must hold:
  * ALLOW / MONITOR / VERIFY  -> unresolved, carry forward
  * SAFE_FALLBACK             -> softened, NOT erased
  * BLOCK / HUMAN_REVIEW / ...-> substantially resolved
"""
from __future__ import annotations

import pytest

from app.controlplane import sessions
from app.controlplane.sessions import (
    _DECAY_PARTIAL,
    _DECAY_RESOLVED,
    _DECAY_UNRESOLVED,
    evaluate_session,
)
from app.core.schemas import Action, AITrace, StepType, TraceStep


def _decay_for(action: Action, inherited: float, turn_risk: float) -> float:
    """Mirror of the loop body so we can unit-test the decay rules directly."""
    if action in sessions._CARRY:
        return max(inherited * _DECAY_UNRESOLVED,
                   turn_risk if turn_risk >= sessions._CARRY_THRESHOLD else 0.0)
    if action in sessions._PARTIAL:
        return max(inherited * _DECAY_PARTIAL, turn_risk * sessions._PARTIAL_RETAIN)
    return inherited * _DECAY_RESOLVED


def test_carry_actions_keep_unresolved_risk_available():
    assert _decay_for(Action.MONITOR, 0.0, 0.5) == 0.5
    assert _decay_for(Action.ALLOW, 0.6, 0.1) == pytest.approx(0.6 * _DECAY_UNRESOLVED)
    assert _decay_for(Action.VERIFY, 0.5, 0.55) == 0.55


def test_safe_fallback_softens_but_does_not_erase():
    out = _decay_for(Action.SAFE_FALLBACK, 0.8, 0.9)
    assert 0 < out < 0.8
    assert out == pytest.approx(max(0.8 * _DECAY_PARTIAL, 0.9 * 0.5))


def test_hard_actions_resolve_substantially():
    for a in (Action.BLOCK, Action.HUMAN_REVIEW, Action.STOP_EXECUTION, Action.MODIFY):
        assert _decay_for(a, 0.9, 0.9) == pytest.approx(0.9 * _DECAY_RESOLVED)
        assert _decay_for(a, 0.9, 0.9) < 0.3


@pytest.mark.asyncio
async def test_inherited_risk_is_written_into_trace_and_step():
    """Both representations the risk engine reads must be populated."""
    turns = [
        AITrace(session_id="s", application="x", workflow="agent_operations",
                request_text="q1", response_text="uncertain answer",
                retrieved_context=["refunds above 5000 dollars need approval",
                                   "refunds up to 10000 dollars are auto-approved"],
                evidence_expected=True,
                steps=[TraceStep(type=StepType.RETRIEVAL, name="kb", duration_ms=80,
                                 retrieved_context=["refunds above 5000 dollars need approval",
                                                    "refunds up to 10000 dollars are auto-approved"],
                                 risk_signals=["conflicting_evidence"]),
                       TraceStep(type=StepType.FINAL_RESPONSE, model="mock-model", duration_ms=200)]),
        AITrace(session_id="s", application="x", workflow="agent_operations",
                request_text="q2 act on it", response_text="ok proceeding",
                steps=[TraceStep(type=StepType.FINAL_RESPONSE, model="mock-model", duration_ms=150)]),
    ]
    result = await evaluate_session(turns)
    assert result.inherited_trace[0] == 0.0
    assert result.inherited_trace[1] > 0.0            # risk carried into turn 2
    assert turns[1].metadata.get("inherited_risk", 0.0) > 0.0
    assert turns[1].steps[-1].inherited_risk > 0.0
