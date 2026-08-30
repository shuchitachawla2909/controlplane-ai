"""Seed the synthetic enterprise + 7 demo scenarios into the local database.

    python scripts/seed_demo.py [--count 5000]
"""
from __future__ import annotations

import argparse
import asyncio

import _bootstrap  # noqa: F401

from app.core.database import session_scope
from app.seed.runner import seed_everything


async def _main(count: int) -> None:
    with session_scope() as s:
        summary = await seed_everything(s, count=count)
    print("Seed complete (all data synthetic):")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5000, help="synthetic historical traces to generate")
    asyncio.run(_main(ap.parse_args().count))
