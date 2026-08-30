"""Learning loop unit behaviour (§15, §49): trust tiers, poisoning guards."""
from __future__ import annotations

from sqlmodel import select

from app.controlplane.learning import (
    FeedbackInput,
    MIN_CANDIDATE_RAW,
    record_feedback,
    validate_case,
)
from app.controlplane.signatures import signature_for
from app.core.models import EvidenceRow, FailurePatternRow, ReviewCaseRow, TraceRow


def _seed_trace(session, tid="trace_x", wf="customer_support", q="Can I get a refund on a return?"):
    row = TraceRow(trace_id=tid, session_id="s1", application="x", workflow=wf,
                   request_preview=q, response_preview="maybe")
    session.add(row)
    session.flush()
    return row


def test_raw_feedback_alone_never_creates_trusted_pattern(db_session):
    _seed_trace(db_session)
    for _ in range(MIN_CANDIDATE_RAW + 2):
        record_feedback(db_session, FeedbackInput(trace_id="trace_x", thumbs="down", reason="incorrect"))
    db_session.flush()
    pat = db_session.exec(select(FailurePatternRow)).first()
    assert pat is not None
    assert pat.status == "candidate"          # NOT trusted
    assert pat.trusted_evidence_count == 0


def test_duplicate_feedback_is_collapsed(db_session):
    _seed_trace(db_session)
    e1 = record_feedback(db_session, FeedbackInput(trace_id="trace_x", thumbs="down", reason="incorrect"))
    e2 = record_feedback(db_session, FeedbackInput(trace_id="trace_x", thumbs="down", reason="incorrect"))
    db_session.flush()
    assert e1.duplicate_of is None
    assert e2.duplicate_of == e1.evidence_id


def test_human_validation_promotes_trusted_pattern(db_session):
    _seed_trace(db_session)
    record_feedback(db_session, FeedbackInput(trace_id="trace_x", thumbs="down", reason="incorrect"))
    db_session.flush()
    case = db_session.exec(select(ReviewCaseRow)).first()
    out = validate_case(db_session, case.case_id, verdict="incorrect", comment="wrong window")
    db_session.flush()
    assert out["pattern_status"] == "trusted"
    ev = db_session.exec(select(EvidenceRow).where(EvidenceRow.kind == "human_validation")).first()
    assert ev.trust_level == "human_validated"


def test_false_positive_validation_cools_pattern_down(db_session):
    _seed_trace(db_session)
    record_feedback(db_session, FeedbackInput(trace_id="trace_x", thumbs="down", reason="incorrect"))
    db_session.flush()
    case = db_session.exec(select(ReviewCaseRow)).first()
    validate_case(db_session, case.case_id, verdict="incorrect", comment="x")
    db_session.flush()
    pat = db_session.exec(select(FailurePatternRow)).first()
    boost_before = pat.risk_boost

    # a later reviewer marks a matching case a false positive
    _seed_trace(db_session, tid="trace_y")
    record_feedback(db_session, FeedbackInput(trace_id="trace_y", thumbs="down", reason="incorrect"))
    db_session.flush()
    case2 = db_session.exec(select(ReviewCaseRow).where(ReviewCaseRow.trace_id == "trace_y")).first()
    validate_case(db_session, case2.case_id, verdict="false_positive")
    db_session.flush()
    db_session.refresh(pat)
    assert pat.risk_boost < boost_before


def test_signature_is_stable_across_paraphrases():
    a = signature_for("customer_support", "Can I return this after 40 days for a refund?")
    b = signature_for("customer_support", "is it possible to send my order back and get money back?")
    assert a == b == "customer_support:return_policy"
