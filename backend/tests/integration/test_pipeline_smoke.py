"""Incremental checkpoint (clarification #11): prove the minimal end-to-end flow
before anything is scaled up.

    trace -> Tier 0 -> parallel Tier 1 -> risk engine -> policy
      -> decision -> intervention -> audit record
"""
from __future__ import annotations

import pytest

from app.core.schemas import Action
from tests.factories import normal_trace


@pytest.mark.asyncio
async def test_minimal_end_to_end(seeded_baselines):
    from app.controlplane.pipeline import evaluate_trace

    trace = normal_trace()
    result = await evaluate_trace(trace, baselines=seeded_baselines)
    rec = result.record

    # Tier 0 populated the normalized observation.
    assert trace.estimated_cost_usd > 0
    assert trace.model_calls >= 1

    # Tier 1 ran and stayed on the fast path; deep eval never touched.
    assert 1 in rec.tiers_run and 0 in rec.tiers_run
    assert 2 not in rec.tiers_run
    assert rec.parallel_check_ms >= 0 and rec.sequential_check_ms >= 0
    # fast-path overhead is small (sub-ms steady state; loose bound for cold JIT)
    assert rec.controlplane_overhead_ms < 400
    assert rec.action == Action.ALLOW

    # Component scores are all present and separate (never just one number).
    for v in (rec.performance_risk, rec.cost_risk, rec.responsibility_risk):
        assert 0.0 <= v <= 1.0
    assert rec.performance_confidence > 0 and rec.cost_confidence > 0

    # Audit record is explainable.
    assert rec.policy_name == "customer_support_v1"
    assert rec.policy_version == "1.0"
    assert rec.what_happened and rec.why_action and rec.what_we_did
    assert rec.safe_response == trace.response_text


@pytest.mark.asyncio
async def test_audit_record_is_persisted(db_session):
    from app.controlplane.pipeline import ingest_and_evaluate
    from app.core.models import DecisionRow, TraceRow

    trace = normal_trace()
    result = await ingest_and_evaluate(trace, db_session)
    db_session.flush()

    assert db_session.get(TraceRow, trace.trace_id) is not None
    drow = db_session.get(DecisionRow, result.record.decision_id)
    assert drow is not None
    assert drow.action == "ALLOW"
    assert drow.policy_version == "1.0"


@pytest.mark.asyncio
async def test_privacy_safe_persistence_redacts_raw_pii(db_session):
    """With CONTROLPLANE_STORE_RAW=false (default), persisted records must not
    retain raw email/phone; detection evidence (entity types) is kept."""
    from app.controlplane.pipeline import ingest_and_evaluate
    from app.core.models import DecisionRow, TraceRow
    from app.seed.scenarios import SCENARIOS

    trace = SCENARIOS["C"].build()   # response contains email + phone, confidential
    result = await ingest_and_evaluate(trace, db_session)
    db_session.flush()

    drow = db_session.get(DecisionRow, result.record.decision_id)
    trow = db_session.get(TraceRow, trace.trace_id)

    for blob in (str(drow.record), str(trow.trace_json), str(trow.steps),
                 trow.request_preview, trow.response_preview):
        assert "john.smith@example.com" not in blob
        assert "98765 43210" not in blob
        assert "+91 98765" not in blob

    assert drow.record["original_response_redacted"] is True
    stored = drow.record["original_response"]
    assert "[EMAIL]" in stored and "[PHONE]" in stored     # masked, not dropped
    # detection evidence is preserved (entity TYPES, not values)
    ev_text = str(drow.record["findings"])
    assert "EMAIL_ADDRESS" in ev_text and "PHONE_NUMBER" in ev_text
    # live in-memory result to the caller is NOT redacted (transient)
    assert "@" in result.record.original_response
