"""Closed-loop learning (§15, §16, §49) — improves the CHECKER, not the LLM.

    production trace -> user feedback -> human / authoritative validation
      -> trusted evidence -> failure-pattern / baseline update -> future routing

Guard rails against feedback poisoning:
* every piece of evidence carries a trust level
  (raw_feedback < machine_evidence < human_validated < authoritative);
* raw user feedback can NEVER promote a trusted failure pattern on its own;
* duplicates (same trace + same source) are collapsed;
* a pattern needs a minimum count of trusted evidence before promotion.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from sqlmodel import Session, select

from app.controlplane.router import LearningContext
from app.controlplane.signatures import signature_for
from app.core.models import (
    DecisionRow,
    EvidenceRow,
    FailurePatternRow,
    GoldenCaseRow,
    ReviewCaseRow,
    TraceRow,
)
from app.core.schemas import Confidence

MIN_CANDIDATE_RAW = 3          # raw feedbacks to raise a *candidate* pattern
MIN_TRUSTED_EVIDENCE = 1       # human/authoritative confirmations to make it *trusted*

_TRUST_WEIGHT = {
    Confidence.RAW_FEEDBACK.value: 0,
    Confidence.MACHINE_EVIDENCE.value: 0,
    Confidence.HUMAN_VALIDATED.value: 1,
    Confidence.AUTHORITATIVE.value: 2,
}
_NEGATIVE_VERDICTS = {"incorrect", "unsafe", "privacy_issue", "biased", "cost_issue", "incomplete", "irrelevant"}


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@dataclass
class FeedbackInput:
    trace_id: str
    thumbs: str                      # "up" | "down"
    reason: str = ""                 # incorrect | incomplete | irrelevant | unsafe | privacy_concern | other
    comment: str = ""
    source: str = "end_user"         # end_user | reviewer | system | authoritative


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
def record_feedback(session: Session, fb: FeedbackInput) -> EvidenceRow:
    trace = session.get(TraceRow, fb.trace_id)
    workflow = trace.workflow if trace else ""
    sig = signature_for(workflow, trace.request_preview if trace else "")

    trust = Confidence.RAW_FEEDBACK.value
    if fb.source == "authoritative":
        trust = Confidence.AUTHORITATIVE.value
    elif fb.source == "reviewer":
        trust = Confidence.HUMAN_VALIDATED.value

    # duplicate detection: same trace + same source + same verdict
    dupe = session.exec(
        select(EvidenceRow).where(
            EvidenceRow.trace_id == fb.trace_id,
            EvidenceRow.source == fb.source,
            EvidenceRow.kind == "user_feedback",
        )
    ).first()

    row = EvidenceRow(
        evidence_id=_uid("ev"),
        trace_id=fb.trace_id,
        session_id=trace.session_id if trace else "",
        workflow=workflow,
        kind="user_feedback",
        trust_level=trust,
        verdict=("negative" if fb.thumbs == "down" else "positive"),
        detail=f"thumbs_{fb.thumbs}" + (f" / {fb.reason}" if fb.reason else ""),
        pattern_signature=sig,
        comment=fb.comment,
        source=fb.source,
        duplicate_of=dupe.evidence_id if dupe else None,
        payload={"reason": fb.reason, "thumbs": fb.thumbs},
    )
    session.add(row)

    # Negative feedback on an un-queued trace -> create a pending review case.
    if fb.thumbs == "down" and trace is not None:
        existing = session.exec(select(ReviewCaseRow).where(ReviewCaseRow.trace_id == fb.trace_id)).first()
        if existing is None:
            session.add(ReviewCaseRow(
                case_id=_uid("case"),
                trace_id=fb.trace_id,
                workflow=workflow,
                reason=f"User reported: {fb.reason or 'thumbs down'}",
                suggested_labels=["incorrect", "incomplete", "unsafe", "privacy_issue", "false_positive"],
                snapshot={"request": trace.request_preview, "response": trace.response_preview},
            ))

    if not dupe:
        _touch_candidate_pattern(session, sig, workflow, row)
    return row


def enqueue_review(session: Session, decision: DecisionRow, reason: str) -> ReviewCaseRow | None:
    if session.exec(select(ReviewCaseRow).where(ReviewCaseRow.trace_id == decision.trace_id)).first():
        return None
    trace = session.get(TraceRow, decision.trace_id)
    case = ReviewCaseRow(
        case_id=_uid("case"),
        trace_id=decision.trace_id,
        decision_id=decision.decision_id,
        workflow=decision.workflow,
        reason=reason,
        suggested_labels=["correct", "incorrect", "unsafe", "privacy_issue", "biased", "cost_issue", "false_positive"],
        snapshot={
            "request": trace.request_preview if trace else "",
            "response": trace.response_preview if trace else "",
            "action": decision.action,
            "overall_risk": decision.overall_risk,
        },
    )
    session.add(case)
    return case


# ---------------------------------------------------------------------------
# Human validation -> trusted evidence
# ---------------------------------------------------------------------------
def validate_case(session: Session, case_id: str, verdict: str, comment: str = "", authoritative: bool = False) -> dict:
    case = session.get(ReviewCaseRow, case_id)
    if case is None:
        raise KeyError(case_id)

    trace = session.get(TraceRow, case.trace_id)
    workflow = case.workflow or (trace.workflow if trace else "")
    sig = signature_for(workflow, (trace.request_preview if trace else ""))
    trust = Confidence.AUTHORITATIVE.value if authoritative else Confidence.HUMAN_VALIDATED.value

    ev = EvidenceRow(
        evidence_id=_uid("ev"),
        trace_id=case.trace_id,
        session_id=trace.session_id if trace else "",
        workflow=workflow,
        kind="human_validation",
        trust_level=trust,
        verdict=verdict,
        detail=f"reviewer verdict: {verdict}",
        pattern_signature=sig,
        comment=comment,
        source="authoritative" if authoritative else "reviewer",
    )
    session.add(ev)

    case.status = "validated" if verdict != "false_positive" else "dismissed"
    case.validated_at = time.time()
    case.validator_verdict = verdict
    case.validator_comment = comment
    case.became_evidence_id = ev.evidence_id
    session.add(case)

    promoted = None
    if verdict in _NEGATIVE_VERDICTS:
        promoted = _touch_candidate_pattern(session, sig, workflow, ev, trusted=True)
        # a confirmed-correct trusted answer also anchors the QUALITY baseline
        if trace and verdict == "incorrect":
            session.add(GoldenCaseRow(
                id=_uid("gold"),
                workflow=workflow,
                pattern_signature=sig,
                question=trace.request_preview,
                trusted_answer=comment or "(reviewer did not supply the corrected answer)",
                dimension="performance",
                trust_level=trust,
            ))
    elif verdict == "false_positive":
        _register_false_positive(session, sig, workflow)

    return {
        "case_id": case_id,
        "status": case.status,
        "evidence_id": ev.evidence_id,
        "pattern": promoted.signature if promoted else None,
        "pattern_status": promoted.status if promoted else None,
    }


def _touch_candidate_pattern(
    session: Session, signature: str, workflow: str, ev: EvidenceRow, trusted: bool = False
) -> FailurePatternRow:
    row = session.exec(select(FailurePatternRow).where(FailurePatternRow.signature == signature)).first()
    if row is None:
        row = FailurePatternRow(
            pattern_id=_uid("fp"),
            signature=signature,
            workflow=workflow,
            dimension="performance",
            description=f"Interactions matching '{signature}' have produced confirmed issues.",
            status="candidate",
            examples=[],
        )
    row.evidence_count += 1
    if _TRUST_WEIGHT.get(ev.trust_level, 0) >= 1:
        row.trusted_evidence_count += _TRUST_WEIGHT[ev.trust_level]
    if ev.detail and len(row.examples) < 5:
        row.examples = [*row.examples, ev.detail]

    if row.trusted_evidence_count >= MIN_TRUSTED_EVIDENCE:
        row.status = "trusted"
        row.risk_boost = min(0.45, 0.25 + 0.05 * row.trusted_evidence_count)
    elif row.evidence_count >= MIN_CANDIDATE_RAW:
        row.status = "candidate"
    row.updated_at = time.time()
    session.add(row)
    return row


def _register_false_positive(session: Session, signature: str, workflow: str) -> None:
    row = session.exec(select(FailurePatternRow).where(FailurePatternRow.signature == signature)).first()
    if row is None:
        return
    # A confirmed false positive cools the pattern down (alert-fatigue control, §48).
    row.risk_boost = max(0.0, row.risk_boost - 0.1)
    if row.risk_boost <= 0.05:
        row.status = "retired"
    row.updated_at = time.time()
    session.add(row)


# ---------------------------------------------------------------------------
# Router-facing context
# ---------------------------------------------------------------------------
def load_learning_context(session: Session, workflow: str) -> LearningContext:
    rows = session.exec(
        select(FailurePatternRow).where(
            FailurePatternRow.workflow == workflow,
            FailurePatternRow.status == "trusted",
        )
    ).all()
    patterns = [
        {
            "pattern_id": r.pattern_id,
            "signature": r.signature,
            "dimension": r.dimension,
            "description": r.description,
            "risk_boost": r.risk_boost,
            "evidence_count": r.evidence_count,
            "trusted_evidence_count": r.trusted_evidence_count,
        }
        for r in rows
    ]
    return LearningContext(trusted_failure_patterns=patterns)


def learning_stats(session: Session) -> dict:
    feedback = session.exec(select(EvidenceRow).where(EvidenceRow.kind == "user_feedback")).all()
    validations = session.exec(select(EvidenceRow).where(EvidenceRow.kind == "human_validation")).all()
    patterns = session.exec(select(FailurePatternRow)).all()
    cases = session.exec(select(ReviewCaseRow)).all()
    return {
        "feedback_received": len(feedback),
        "cases_total": len(cases),
        "cases_pending": sum(1 for c in cases if c.status == "pending"),
        "cases_validated": sum(1 for c in cases if c.status == "validated"),
        "false_positives": sum(1 for c in cases if c.validator_verdict == "false_positive"),
        "validated_failures": sum(1 for v in validations if v.verdict in _NEGATIVE_VERDICTS),
        "candidate_patterns": sum(1 for p in patterns if p.status == "candidate"),
        "trusted_patterns": sum(1 for p in patterns if p.status == "trusted"),
        "golden_cases": len(session.exec(select(GoldenCaseRow)).all()),
    }
