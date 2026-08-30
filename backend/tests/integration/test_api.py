from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.database import reset_db
from app.main import app


@pytest.fixture()
def client():
    reset_db()
    with TestClient(app) as c:
        yield c


def test_health_and_root(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").json()["positioning"] == "Adaptive Runtime AI Oversight"


def test_scenario_run_then_trace_detail(client):
    r = client.post("/api/demo/run/B")
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["action"] in {"MODIFY", "VERIFY", "BLOCK", "HUMAN_REVIEW"}
    tid = body["trace_id"]

    detail = client.get(f"/api/traces/{tid}").json()
    assert detail["trace"]["trace_id"] == tid
    assert detail["decision"]["policy_version"] == "1.0"
    # component scores exposed, not just overall
    for k in ("performance_risk", "cost_risk", "responsibility_risk"):
        assert k in detail["decision"]


def test_ingest_feedback_review_learning_flow(client):
    # ingest a weak trace
    trace = {
        "application": "Customer Support Assistant", "workflow": "customer_support",
        "request_text": "Can I return this for a refund after a while?",
        "response_text": "Refunds for returns are handled case by case by support.",
        "retrieved_context": ["Refunds for returns are handled case by case by support."],
        "evidence_expected": True,
        "steps": [{"type": "final_response", "model": "mock-model",
                   "usage": {"input_tokens": 200, "output_tokens": 70}, "duration_ms": 600}],
    }
    ing = client.post("/api/traces", json={"trace": trace}).json()
    tid = ing["trace_id"]

    fb = client.post("/api/feedback", json={"trace_id": tid, "thumbs": "down", "reason": "incorrect"}).json()
    assert fb["trust_level"] == "raw_feedback"

    queue = client.get("/api/review-queue").json()
    assert any(c["trace_id"] == tid for c in queue)
    case_id = next(c["case_id"] for c in queue if c["trace_id"] == tid)

    val = client.post(f"/api/review/{case_id}", json={"verdict": "incorrect", "comment": "30 day window"}).json()
    assert val["pattern_status"] == "trusted"

    learning = client.get("/api/metrics/learning").json()
    assert learning["trusted_patterns"] >= 1


def test_policies_versioning(client):
    before = client.get("/api/policies/customer_support").json()
    assert before["active"]["version"] == "1.0"
    upd = client.put("/api/policies/customer_support",
                     json={"body": {"routing": {"fast_path_below": 0.2}}, "note": "tighten"}).json()
    assert upd["new_version"] == "1.1"
    after = client.get("/api/policies/customer_support").json()
    assert after["active"]["version"] == "1.1"
    assert len(after["versions"]) >= 2


def test_metrics_overview_shape(client):
    for key in ("A", "C", "E"):
        client.post(f"/api/demo/run/{key}")
    ov = client.get("/api/metrics/overview").json()
    assert ov["total_interactions"] >= 3
    assert "fast_path_rate" in ov and "risk_distribution" in ov
