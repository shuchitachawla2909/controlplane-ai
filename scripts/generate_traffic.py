"""Generate synthetic AI traffic and (optionally) push it through the pipeline.

    python scripts/generate_traffic.py --count 10000 --profile mixed
    python scripts/generate_traffic.py --count 2000 --profile customer_support --dump data/synthetic/cs.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import _bootstrap

from app.controlplane.baselines import BaselineProvider
from app.controlplane.router import run_pipeline
from app.seed.data import WORKFLOWS, generate

PROFILES = ("mixed", *WORKFLOWS)


async def _run(count: int, profile: str, seed: int, dump: str | None, process: bool) -> None:
    traces = list(generate(count, seed=seed, profile=profile))
    if dump:
        path = _bootstrap._REPO / dump
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for t in traces:
                fh.write(json.dumps(t.model_dump(mode="json")) + "\n")
        print(f"Wrote {len(traces)} traces -> {path}")

    if not process:
        return

    bps = {wf: BaselineProvider(wf) for wf in WORKFLOWS}
    for t in generate(400, seed=seed + 1):
        if t.metadata.get("truth", {}).get("category") == "normal":
            bps[t.workflow].observe_trace(t)

    start = time.perf_counter()
    actions: dict[str, int] = {}
    deep = 0
    for t in traces:
        rec = (await run_pipeline(t, baselines=bps.get(t.workflow))).record
        actions[rec.action.value] = actions.get(rec.action.value, 0) + 1
        deep += int(2 in rec.tiers_run)
    elapsed = time.perf_counter() - start
    print(f"Processed {count} traces in {elapsed:.2f}s ({count / elapsed:.0f}/s)")
    print(f"  deep-check rate: {deep / count:.1%}")
    print(f"  actions: {actions}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10000)
    ap.add_argument("--profile", choices=PROFILES, default="mixed")
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--dump", type=str, default=None, help="write traces as JSONL to this repo-relative path")
    ap.add_argument("--no-process", action="store_true", help="only generate, do not run the pipeline")
    a = ap.parse_args()
    asyncio.run(_run(a.count, a.profile, a.seed, a.dump, not a.no_process))
