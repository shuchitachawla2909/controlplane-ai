"""Operational baseline engine (§13, §62, §63).

Robust statistics only — a single spike must not teach the system that
anomalous behaviour is normal. Cold-start workflows report LOW confidence
instead of pretending the baseline is reliable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from sqlmodel import Session, select

from app.core.models import BaselineRow
from app.core.schemas import AITrace

MAX_WINDOW = 250
MIN_SAMPLES = 25                 # below this -> cold start, low baseline confidence
_TRACKED_METRICS = ("latency_ms", "total_tokens", "model_calls", "tool_calls", "cost_usd", "retries")


def trace_metrics(trace: AITrace) -> dict[str, float]:
    # Ensure Tier 0 derived fields exist (idempotent). A raw trace built by a
    # caller/factory has zeros until it is observed.
    if trace.steps and trace.estimated_cost_usd == 0.0 and trace.latency_ms == 0.0:
        from app.controlplane.observer import observe

        observe(trace)
    return {
        "latency_ms": float(trace.latency_ms),
        "total_tokens": float(trace.total_input_tokens + trace.total_output_tokens),
        "model_calls": float(trace.model_calls),
        "tool_calls": float(trace.tool_calls),
        "cost_usd": float(trace.estimated_cost_usd),
        "retries": float(trace.retries),
    }


@dataclass
class RobustBaseline:
    metric: str
    window: list[float] = field(default_factory=list)
    quarantined: list[float] = field(default_factory=list)

    # cached stats
    n: int = 0
    median: float = 0.0
    p95: float = 0.0
    mad: float = 0.0
    mean: float = 0.0

    def recompute(self) -> None:
        if not self.window:
            self.n = 0
            self.median = self.p95 = self.mad = self.mean = 0.0
            return
        arr = np.asarray(self.window, dtype=float)
        self.n = int(arr.size)
        self.median = float(np.median(arr))
        self.p95 = float(np.percentile(arr, 95))
        self.mean = float(np.mean(arr))
        self.mad = float(np.median(np.abs(arr - self.median)))

    @property
    def confidence(self) -> float:
        if self.n <= 0:
            return 0.0
        return round(min(1.0, self.n / MIN_SAMPLES), 3)

    @property
    def is_cold_start(self) -> bool:
        return self.n < MIN_SAMPLES

    def _scale(self) -> float:
        # 1.4826 * MAD approximates the standard deviation for normal data.
        if self.mad > 1e-9:
            return 1.4826 * self.mad
        if self.median > 1e-9:
            return 0.25 * self.median      # fallback dispersion
        return 1.0

    def robust_z(self, x: float) -> float:
        if self.n == 0:
            return 0.0
        return (x - self.median) / self._scale()

    def multiplier(self, x: float) -> float:
        denom = self.median
        if denom <= 1e-9:
            denom = self.p95 if self.p95 > 1e-9 else (self.mean if self.mean > 1e-9 else 0.0)
        if denom <= 1e-9:
            # No usable central tendency (e.g. retries are normally zero) —
            # we cannot express this as a ratio, so report "no signal".
            return 1.0
        return x / denom

    def observe(self, x: float, is_anomaly: bool) -> None:
        """Quarantine anomalies; only clean samples update the live window."""
        if is_anomaly:
            self.quarantined.append(float(x))
            self.quarantined = self.quarantined[-50:]
            return
        self.window.append(float(x))
        if len(self.window) > MAX_WINDOW:
            self.window = self.window[-MAX_WINDOW:]
        self.recompute()

    def to_row_fields(self) -> dict:
        return {
            "n": self.n, "median": self.median, "p95": self.p95,
            "mad": self.mad, "mean": self.mean,
            "window": self.window, "quarantined": self.quarantined,
        }


class BaselineProvider:
    """Per-workflow view over the baseline store. Works with or without a DB."""

    def __init__(self, workflow: str, session: Session | None = None):
        self.workflow = workflow
        self.session = session
        self._cache: dict[str, RobustBaseline] = {}
        if session is not None:
            self._load()

    def _load(self) -> None:
        assert self.session is not None
        rows = self.session.exec(
            select(BaselineRow).where(BaselineRow.workflow == self.workflow)
        ).all()
        for row in rows:
            b = RobustBaseline(
                metric=row.metric,
                window=list(row.window or []),
                quarantined=list(row.quarantined or []),
            )
            b.recompute()
            self._cache[row.metric] = b

    def get(self, metric: str) -> RobustBaseline:
        if metric not in self._cache:
            self._cache[metric] = RobustBaseline(metric=metric)
        return self._cache[metric]

    @property
    def confidence(self) -> float:
        """Overall baseline confidence for this workflow (min across core metrics)."""
        core = [self.get(m).confidence for m in ("latency_ms", "cost_usd", "model_calls")]
        return round(min(core), 3) if core else 0.0

    def seed_many(self, traces: Iterable[AITrace]) -> None:
        for tr in traces:
            for metric, value in trace_metrics(tr).items():
                self.get(metric).observe(value, is_anomaly=False)

    def observe_trace(self, trace: AITrace, anomalous_metrics: set[str] | None = None) -> None:
        anomalous_metrics = anomalous_metrics or set()
        for metric, value in trace_metrics(trace).items():
            self.get(metric).observe(value, is_anomaly=metric in anomalous_metrics)

    def persist(self) -> None:
        if self.session is None:
            return
        for metric in _TRACKED_METRICS:
            b = self._cache.get(metric)
            if b is None:
                continue
            key = f"{self.workflow}:{metric}"
            row = self.session.get(BaselineRow, key)
            fields = b.to_row_fields()
            if row is None:
                row = BaselineRow(key=key, workflow=self.workflow, metric=metric, **fields)
            else:
                for k, v in fields.items():
                    setattr(row, k, v)
            self.session.add(row)
