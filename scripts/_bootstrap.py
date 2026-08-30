"""Shared path/env setup for the CLI scripts."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("LLM_PROVIDER", "mock")

RESULTS_DIR = _REPO / "results"
DATA_DIR = _REPO / "data"
RESULTS_DIR.mkdir(exist_ok=True)
