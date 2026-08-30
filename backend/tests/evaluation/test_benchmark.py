from __future__ import annotations

import pytest

from app.controlplane.benchmark import run_benchmark


@pytest.mark.asyncio
async def test_benchmark_report_has_three_labeled_tiers():
    res = await run_benchmark(count=180, seed=3, with_learning_effect=True,
                              deep_eval_sim_latency_ms=300.0)

    # --- report structure -------------------------------------------------
    for tier in ("structural", "runtime_local", "simulated_cost"):
        assert tier in res and "note" in res[tier]
    assert res["deep_eval_sim_latency_ms"] == 300.0
    assert "arms" in res  # backward-compatible flat view retained

    s = res["structural"]
    a, b, c = s["A_no_checker"], s["B_always_deep"], s["C_controlplane"]

    # --- structural (deterministic) claims ------------------------------
    assert a["recall"] == 0.0                       # a no-op detects nothing
    assert b["deep_eval_pct"] == 1.0               # always-deep checks everything deeply
    assert c["fast_path_pct"] >= 0.6               # ControlPlane keeps most traffic on the fast path
    if b["recall"]:
        assert c["recall"] >= 0.9 * b["recall"]    # comparable detection coverage
    assert s["recall_retained_vs_always_deep"] is not None
    assert "uncertainty_handling" in s

    # --- runtime is labeled, not headlined -----------------------------
    rl = res["runtime_local"]
    assert "not portable" in rl["note"] or "not portable" in rl["note"].lower()
    b_r, c_r = rl["B_always_deep"], rl["C_controlplane"]
    # the sim-latency illustration must add ~300ms to B's deep path
    assert b_r["illustrative_p95_with_sim_deep_latency_ms"] >= b_r["measured_p95_overhead_ms"] + 290

    # --- simulated cost is labeled as a model -------------------------
    assert "NOT production financial savings" in res["simulated_cost"]["note"]
    assert res["simulated_cost"]["unit_price_usd"] > 0

    # --- learning effect is a labeled simulation ---------------------
    le = res["north_star"]["learning_effect"]
    assert le["simulated"] is True
    assert le["after"]["recall"] >= le["before"]["recall"] - 0.05
