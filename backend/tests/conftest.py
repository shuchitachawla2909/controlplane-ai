from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `app` importable and force the offline provider for all tests.
_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("CONTROLPLANE_DB_URL", "sqlite:///./test_controlplane.db")


@pytest.fixture(autouse=True)
def _fresh_policy_store():
    """Policy store is a process-wide singleton; reset it around every test so a
    PUT /api/policies in one test cannot leak a bumped version into another."""
    from app.controlplane.policy_engine import get_policy_store

    get_policy_store.cache_clear()
    yield
    get_policy_store.cache_clear()


@pytest.fixture()
def db_session():
    """Isolated in-memory-ish DB per test (file db, reset each time)."""
    from app.core.database import reset_db, session_scope

    reset_db()
    with session_scope() as s:
        yield s


@pytest.fixture()
def seeded_baselines():
    """A BaselineProvider primed with ~40 'normal' customer-support traces."""
    from app.controlplane.baselines import BaselineProvider
    from tests.factories import normal_trace

    bp = BaselineProvider("customer_support")
    bp.seed_many(normal_trace() for _ in range(40))
    return bp
