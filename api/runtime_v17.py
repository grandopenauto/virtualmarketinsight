from __future__ import annotations

from typing import Any

import api.runtime_v16 as previous
from api.decision_refresh import (
    get_decision_refresh,
    list_decision_refreshes,
    prepare_decision_refresh,
    verify_decision_refresh_chain,
)

previous.base.VERSION = "0.17.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/decision-refreshes/schema")
def operator_decision_refresh_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.decision-refresh.v1",
        "purpose": "Combine one immutable evidence return with its prior decision context to create a new human-review snapshot without creating approval or execution authority.",
        "one_refresh_per_evidence_return": True,
        "automatic_gap_resolution": False,
        "approval_recorded_by_refresh": False,
        "execution_permitted_by_refresh": False,
        "dispatch_permitted_by_refresh": False,
        "external_actions_executed": 0,
    }


@app.post("/api/v1/operator/evidence-returns/{evidence_return_id}/decision-refresh/prepare")
def operator_prepare_decision_refresh(
    evidence_return_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        packet = prepare_decision_refresh(evidence_return_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.decision-refresh-receipt.v1",
        "packet": packet,
        "state": "refreshed_for_human_review",
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": packet["next_gate"],
    }


@app.get("/api/v1/operator/decision-refreshes")
def operator_decision_refresh_list(
    limit: int = 50,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    items = list_decision_refreshes(limit)
    return {
        "schema": "vmi.decision-refresh.v1",
        "items": items,
        "count": len(items),
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/decision-refreshes/verify")
def operator_decision_refresh_verify(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return verify_decision_refresh_chain()


@app.get("/api/v1/operator/decision-refreshes/{refresh_id}")
def operator_decision_refresh_get(
    refresh_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    item = get_decision_refresh(refresh_id, include_payload=True)
    if not item:
        raise base.HTTPException(status_code=404, detail="Decision refresh packet not found.")
    return {
        "schema": "vmi.decision-refresh.v1",
        "item": item,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
