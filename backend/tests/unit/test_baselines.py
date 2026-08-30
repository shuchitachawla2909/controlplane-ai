from __future__ import annotations

from app.controlplane.baselines import MIN_SAMPLES, RobustBaseline


def test_cold_start_reports_low_confidence():
    b = RobustBaseline(metric="cost_usd")
    for _ in range(5):
        b.observe(0.02, is_anomaly=False)
    assert b.is_cold_start
    assert b.confidence < 1.0


def test_robust_stats_and_multiplier():
    b = RobustBaseline(metric="cost_usd")
    for _ in range(MIN_SAMPLES + 10):
        b.observe(0.02, is_anomaly=False)
    assert not b.is_cold_start
    assert abs(b.median - 0.02) < 1e-6
    assert b.multiplier(0.06) == 3.0
    assert abs(b.multiplier(0.02) - 1.0) < 1e-6


def test_anomaly_is_quarantined_not_learned():
    b = RobustBaseline(metric="cost_usd")
    for _ in range(MIN_SAMPLES + 5):
        b.observe(0.02, is_anomaly=False)
    median_before = b.median
    b.observe(0.80, is_anomaly=True)          # severe anomaly
    assert b.median == median_before          # window unchanged
    assert 0.80 in b.quarantined


def test_zero_normal_metric_yields_no_false_signal():
    b = RobustBaseline(metric="retries")
    for _ in range(MIN_SAMPLES + 5):
        b.observe(0.0, is_anomaly=False)
    # retries are normally zero -> a single retry must not read as "3x runaway"
    assert b.multiplier(1.0) == 1.0
