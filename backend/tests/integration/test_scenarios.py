"""End-to-end checks for the seven required demo scenarios (§36).

The pipeline computes every decision; the scenario only supplies inputs.
"""
from __future__ import annotations

import pytest

from app.controlplane.baselines import BaselineProvider
from app.controlplane.pipeline import evaluate_trace
from app.controlplane.sessions import evaluate_session
from app.seed.data import generate
from app.seed.scenarios import SCENARIOS


def _baselines() -> dict[str, BaselineProvider]:
    bps: dict[str, BaselineProvider] = {}
    for wf in ("customer_support", "internal_assistant", "decision_support", "agent_operations"):
        bps[wf] = BaselineProvider(wf)
    for tr in generate(400, seed=7):
        if tr.metadata.get("truth", {}).get("category") == "normal":
            bps[tr.workflow].observe_trace(tr)
    return bps


BASELINES = _baselines()


@pytest.mark.parametrize("key", ["A", "B", "C", "C2", "D", "E", "F"])
@pytest.mark.asyncio
async def test_single_turn_scenarios(key):
    sc = SCENARIOS[key]
    trace = sc.build()
    result = await evaluate_trace(trace, baselines=BASELINES[sc.workflow])
    rec = result.record
    assert rec.action.value in sc.expected["expected_action"], (
        f"scenario {key}: got {rec.action.value}, expected one of {sc.expected['expected_action']}"
    )
    if key == "C":
        assert rec.action.value == "BLOCK"          # confidential -> block
    if key == "C2":
        assert rec.action.value == "MODIFY" and rec.modification_method == "redaction"
        assert "jordan.lee@example.com" not in rec.safe_response
        assert "415 555 0142" not in rec.safe_response
        assert "REDACTED" in rec.safe_response
    if key == "A":
        assert rec.tier == 1 and rec.action.value == "ALLOW"
        # Steady-state fast-path overhead is sub-millisecond (see the benchmark);
        # this only guards against a Tier-2 path sneaking in. Loose bound covers
        # one-time import/JIT cost on the first pipeline call in a cold process.
        assert rec.controlplane_overhead_ms < 400
        assert rec.parallel_check_ms < rec.controlplane_overhead_ms
    if key == "B":
        assert "authoritative_contradiction" in [f.label for f in result.findings]
    if key == "D":
        assert rec.evidence_confidence < 0.5 and rec.ground_truth_available is False
    if key == "E":
        assert rec.execution_stopped and rec.prevented_spend_usd > 0
    if key == "F":
        assert "bias_signal" in [f.label for f in result.findings]


@pytest.mark.asyncio
async def test_scenario_g_multi_turn_compounding_risk():
    turns = SCENARIOS["G"].build()
    session = await evaluate_session(turns, baselines=BASELINES["agent_operations"])
    t0, t1, t2 = (pr.record for pr in session.turns)

    # 1. turn 0 raises risk from conflicting evidence but does NOT hard-resolve it
    assert t0.action.value in {"MONITOR", "VERIFY"}
    assert any("conflict" in r.lower() for r in t0.reasons)

    # 2. inherited risk is > 0 after the first unresolved turn and does not shrink
    assert session.inherited_trace[0] == 0.0
    assert session.inherited_trace[1] > 0.0
    assert session.inherited_trace[2] >= session.inherited_trace[1]      # remains / increases

    # 3. the middle turn is acting on inherited risk, not its own violation
    assert "inherited_risk" in session.turns[1].risk.performance.labels
    assert any("inherited" in r.lower() for r in t1.reasons)

    # 4. the final consequential turn is hard-gated BECAUSE of compounding risk
    assert t2.action.value == "HUMAN_REVIEW"
    assert session.turns[2].risk.consequential_action is True
    assert session.turns[2].risk.inherited_risk >= 0.4
    assert any("compounding" in r.lower() or "earlier" in r.lower() for r in t2.reasons)

    # 5. turn 3 carries NO retrieval context of its own -> escalation is inherited,
    #    not "turn 3 independently looked dangerous"
    assert not turns[2].retrieved_context
    assert session.turns[2].risk.performance.risk < 0.2 or \
        "inherited_risk" in session.turns[2].risk.performance.labels
