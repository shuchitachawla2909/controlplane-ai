"""Shared seeding routine used by both `scripts/seed_demo.py` and POST /api/demo/seed.

Populates a realistic-looking system: synthetic history, the 7 curated demo
scenarios (processed by the REAL engine), plus enough feedback + human
validations that the Review Queue and Learning Loop pages are non-empty.
"""
from __future__ import annotations

import random

from sqlmodel import Session, select

from app.api.policies import sync_policies_to_db
from app.controlplane.baselines import BaselineProvider
from app.controlplane.learning import FeedbackInput, record_feedback, validate_case
from app.controlplane.pipeline import ingest_and_evaluate, persist_result
from app.controlplane.sessions import evaluate_session
from app.core.database import reset_db
from app.core.models import DecisionRow, ReviewCaseRow
from app.seed.data import WORKFLOWS, generate
from app.seed.scenarios import SCENARIOS


async def seed_everything(session: Session, *, count: int = 1200, seed: int = 1729, fresh: bool = True) -> dict:
    if fresh:
        reset_db()
    sync_policies_to_db(session)

    # 1. Warm per-workflow operational baselines from NORMAL traffic only.
    bps = {wf: BaselineProvider(wf, session) for wf in WORKFLOWS}
    for tr in generate(max(500, count // 2), seed=seed + 1):
        if tr.metadata.get("truth", {}).get("category") == "normal":
            bps[tr.workflow].observe_trace(tr)
    for bp in bps.values():
        bp.persist()
    session.flush()

    # 2. Main synthetic history — processed end to end by the real pipeline.
    actions: dict[str, int] = {}
    tiers: dict[int, int] = {}
    for tr in generate(count, seed=seed):
        res = await ingest_and_evaluate(tr, session)
        a = res.record.action.value
        actions[a] = actions.get(a, 0) + 1
        tiers[res.record.tier] = tiers.get(res.record.tier, 0) + 1
    session.flush()

    # 3. The seven curated demo scenarios.
    scenario_results = []
    for key, sc in SCENARIOS.items():
        built = sc.build()
        if sc.multi_turn:
            sr = await evaluate_session(built, baselines=BaselineProvider(sc.workflow, session))
            for turn, pr in zip(built, sr.turns):
                persist_result(session, turn, pr)
            scenario_results.append({"key": key, "action": sr.turns[-1].record.action.value, "multi_turn": True})
        else:
            pr = await ingest_and_evaluate(built, session)
            scenario_results.append({"key": key, "action": pr.record.action.value, "trace_id": built.trace_id})
    session.flush()

    # 4. Feedback + human validation so the learning loop has real content.
    rng = random.Random(seed)
    flagged = session.exec(
        select(DecisionRow).where(DecisionRow.action.in_(["MODIFY", "VERIFY", "MONITOR", "HUMAN_REVIEW", "SAFE_FALLBACK"]))
    ).all()
    rng.shuffle(flagged)
    fb_count = val_count = 0
    for d in flagged[:60]:
        thumbs = "down" if rng.random() < 0.7 else "up"
        record_feedback(session, FeedbackInput(trace_id=d.trace_id, thumbs=thumbs,
                                               reason=rng.choice(["incorrect", "incomplete", "unsafe", "other"])))
        fb_count += 1
    session.flush()
    pending = session.exec(select(ReviewCaseRow).where(ReviewCaseRow.status == "pending")).all()
    for c in pending[: max(1, len(pending) // 2)]:
        verdict = rng.choice(["incorrect", "incorrect", "false_positive", "unsafe", "correct"])
        validate_case(session, c.case_id, verdict=verdict, comment="seed validation")
        val_count += 1
    session.flush()

    return {
        "synthetic": True,
        "history_traces": count,
        "action_distribution": actions,
        "tier_distribution": tiers,
        "scenarios": scenario_results,
        "feedback_created": fb_count,
        "cases_validated": val_count,
        "note": "All data is synthetic. Decisions were computed by the real risk engine, not hard-coded.",
    }
