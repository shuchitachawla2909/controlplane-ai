from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.api.deps import get_session
from app.controlplane import analytics
from app.controlplane.learning import learning_stats
from app.core.models import BenchmarkRunRow, DecisionRow, EvidenceRow, TraceRow

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _decisions(session: Session, limit: int = 20000) -> list[DecisionRow]:
    return session.exec(select(DecisionRow).order_by(DecisionRow.created_at.desc()).limit(limit)).all()


@router.get("/overview")
def metrics_overview(session: Session = Depends(get_session)):
    decisions = _decisions(session)
    total_spend = session.exec(select(func.coalesce(func.sum(TraceRow.estimated_cost_usd), 0.0))).one()
    ov = analytics.overview(decisions, total_spend=float(total_spend))
    ov["timeseries"] = analytics.timeseries(decisions)["buckets"]
    ov["feedback_trend"] = _feedback_trend(session)
    return ov


@router.get("/risk")
def metrics_risk(session: Session = Depends(get_session)):
    return analytics.risk_breakdown(_decisions(session))


@router.get("/latency")
def metrics_latency(session: Session = Depends(get_session)):
    return analytics.latency_report(_decisions(session))


@router.get("/learning")
def metrics_learning(session: Session = Depends(get_session)):
    stats = learning_stats(session)
    stats["deep_check_rate_over_time"] = analytics.timeseries(_decisions(session))["buckets"]
    latest = session.exec(
        select(BenchmarkRunRow).order_by(BenchmarkRunRow.created_at.desc()).limit(1)
    ).first()
    if latest and "learning_effect" in (latest.north_star or {}):
        stats["learning_effect"] = latest.north_star["learning_effect"]
    return stats


def _feedback_trend(session: Session, buckets: int = 10) -> list[dict]:
    rows = session.exec(select(EvidenceRow).where(EvidenceRow.kind == "user_feedback")).all()
    if not rows:
        return []
    rows.sort(key=lambda r: r.created_at)
    t0, t1 = rows[0].created_at, rows[-1].created_at or rows[0].created_at + 1
    span = max(t1 - t0, 1e-6)
    out: dict[int, dict] = {}
    for r in rows:
        b = min(buckets - 1, int((r.created_at - t0) / span * buckets))
        slot = out.setdefault(b, {"bucket": b, "positive": 0, "negative": 0})
        slot["negative" if r.verdict == "negative" else "positive"] += 1
    return [out[b] for b in sorted(out)]
