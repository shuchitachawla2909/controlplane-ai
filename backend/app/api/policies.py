from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_session
from app.api.io import PolicyUpdateRequest
from app.controlplane.policy_engine import get_policy_store
from app.core.models import PolicyRow

router = APIRouter(prefix="/api", tags=["policies"])


def sync_policies_to_db(session: Session) -> None:
    """Persist file-defined policies as the first version if not already present."""
    store = get_policy_store()
    for workflow, body in store.policies().items():
        pid = f"{body.get('name', workflow)}:{body.get('version', '1.0')}"
        if session.get(PolicyRow, pid) is None:
            session.add(PolicyRow(
                id=pid, name=body.get("name", f"{workflow}_policy"),
                version=str(body.get("version", "1.0")), workflow=workflow, active=True,
                source="file", body=body,
            ))


def _bump(version: str) -> str:
    try:
        major, minor = version.split(".")[:2]
        return f"{major}.{int(minor) + 1}"
    except Exception:  # noqa: BLE001
        return f"{version}.1"


@router.get("/policies")
def list_policies(session: Session = Depends(get_session)):
    store = get_policy_store()
    profiles = store.workflows()
    out = []
    for workflow in store.policies():
        p = store.resolve(workflow)
        out.append({
            "workflow": workflow,
            "name": p.name,
            "version": p.version,
            "risk_class": p.profile.get("risk_class"),
            "latency_budget_ms": p.latency_budget_ms,
            "cost_budget_usd": p.cost_budget_usd,
            "thresholds": p.body.get("thresholds", {}),
            "routing": p.routing(),
            "human_review": p.body.get("human_review", {}),
            "data_policy": p.body.get("data_policy", {}),
            "profile": profiles.get(workflow, {}),
        })
    return out


@router.get("/policies/{workflow}")
def get_policy(workflow: str, session: Session = Depends(get_session)):
    store = get_policy_store()
    if workflow not in store.policies():
        raise HTTPException(404, "unknown workflow")
    p = store.resolve(workflow)
    history = session.exec(
        select(PolicyRow).where(PolicyRow.workflow == workflow).order_by(PolicyRow.created_at.desc())
    ).all()
    return {
        "workflow": workflow,
        "active": {"name": p.name, "version": p.version, "body": p.body, "profile": p.profile},
        "versions": [{"id": h.id, "version": h.version, "active": h.active,
                      "created_at": h.created_at, "source": h.source} for h in history],
    }


@router.put("/policies/{workflow}")
def update_policy(workflow: str, req: PolicyUpdateRequest, session: Session = Depends(get_session)):
    """Edit a policy -> creates a NEW version. Traces keep the version they ran under."""
    store = get_policy_store()
    if workflow not in store.policies():
        raise HTTPException(404, "unknown workflow")
    current = store.resolve(workflow)
    new_version = _bump(current.version)
    new_body = {**current.body, **req.body, "name": current.name, "version": new_version, "workflow": workflow}

    for h in session.exec(select(PolicyRow).where(PolicyRow.workflow == workflow, PolicyRow.active)).all():
        h.active = False
        session.add(h)
    row = PolicyRow(
        id=f"{current.name}:{new_version}", name=current.name, version=new_version,
        workflow=workflow, active=True, created_at=time.time(), source="edited", body=new_body,
    )
    session.add(row)
    store.register(workflow, new_body, store.workflows().get(workflow))
    return {"workflow": workflow, "new_version": new_version, "note": req.note,
            "body": new_body}
