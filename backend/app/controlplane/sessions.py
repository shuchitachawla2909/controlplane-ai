"""Multi-turn session evaluation with risk inheritance (§21, §22).

A session is an ordered list of turns (each a full :class:`AITrace`). Unresolved
risk from an earlier turn is threaded forward as ``inherited_risk`` so that a
later consequential action escalates even if that turn, in isolation, looks
benign. This is a GENERAL mechanism — there is no scenario-specific branching.

Resolution semantics (the conceptual distinction that matters):

* ALLOW / MONITOR / VERIFY  -> the underlying question was NOT resolved; carry
  the turn's risk forward (lightly decayed).
* SAFE_FALLBACK             -> we returned a safe non-answer; this REDUCES but
  does NOT erase the unresolved uncertainty ("a fallback" != "resolved").
* BLOCK / STOP_EXECUTION / HUMAN_REVIEW / MODIFY -> the risk was substantially
  handled; decay it hard.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.controlplane.baselines import BaselineProvider
from app.controlplane.router import LearningContext, PipelineResult, run_pipeline
from app.core.schemas import Action, AITrace

_CARRY = {Action.ALLOW, Action.MONITOR, Action.VERIFY}       # unresolved
_PARTIAL = {Action.SAFE_FALLBACK}                            # softened, not resolved
# everything else (BLOCK / STOP_EXECUTION / HUMAN_REVIEW / MODIFY) resolves hard

_DECAY_UNRESOLVED = 0.85
_DECAY_PARTIAL = 0.6
_DECAY_RESOLVED = 0.25
_CARRY_THRESHOLD = 0.30     # turn risk at/above which unresolved risk starts to accumulate
_PARTIAL_RETAIN = 0.5       # fraction of the turn's own risk a fallback still leaves on the table


@dataclass
class SessionResult:
    session_id: str
    turns: list[PipelineResult] = field(default_factory=list)
    inherited_trace: list[float] = field(default_factory=list)   # risk carried INTO turn i
    residual_trace: list[float] = field(default_factory=list)     # risk carried OUT of turn i

    @property
    def final(self) -> PipelineResult:
        return self.turns[-1]


async def evaluate_session(
    turns: list[AITrace],
    *,
    learning: LearningContext | None = None,
    baselines: BaselineProvider | None = None,
) -> SessionResult:
    inherited = 0.0
    out = SessionResult(session_id=turns[0].session_id if turns else "")

    for i, turn in enumerate(turns):
        turn.turn_index = i
        turn.session_id = out.session_id or turn.session_id

        if inherited > 0:
            # thread the inherited risk into BOTH representations the risk engine
            # reads (trace metadata and the terminal step), so the mechanism is
            # genuinely wired rather than merely represented.
            prev = float(turn.metadata.get("inherited_risk", 0.0))
            turn.metadata["inherited_risk"] = max(prev, round(inherited, 4))
            if turn.steps:
                turn.steps[-1].inherited_risk = max(turn.steps[-1].inherited_risk, round(inherited, 4))

        out.inherited_trace.append(round(inherited, 4))
        result = await run_pipeline(turn, learning=learning, baselines=baselines)
        out.turns.append(result)

        rec = result.record
        turn_risk = max(rec.performance_risk, rec.responsibility_risk)
        if rec.action in _CARRY:
            inherited = max(inherited * _DECAY_UNRESOLVED,
                            turn_risk if turn_risk >= _CARRY_THRESHOLD else 0.0)
        elif rec.action in _PARTIAL:
            inherited = max(inherited * _DECAY_PARTIAL, turn_risk * _PARTIAL_RETAIN)
        else:
            inherited *= _DECAY_RESOLVED

        out.residual_trace.append(round(inherited, 4))

    return out
