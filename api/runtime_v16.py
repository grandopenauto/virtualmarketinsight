from __future__ import annotations

from typing import Any

import api.runtime_v15 as previous
from api.evidence_return import (
    get_evidence_return,
    list_evidence_returns,
    prepare_evidence_return,
    verify_evidence_return_chain,
)

previous.base.VERSION = "0.16.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/evidence-returns/schema")
def operator_evidence_return_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.evidence-return.v1",
        "purpose": "Return one completed read-only execution result into its originating review lineage as immutable evidence for a later human-reviewed decision refresh.",
        "completed_execution_required": True,
        "one_return_per_execution_receipt": True,
        "approval_recorded_by_return": False,
        "execution_permitted_by_return": False,
        "dispatch_permitted_by_return": False,
        "automatic_decision_refresh": False,
        "external_actions_executed": 0,
    }


@app.post("/api/v1/operator/read-only-executions/{execution_receipt_id}/evidence-return/prepare")
def operator_prepare_evidence_return(
    execution_receipt_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        packet = prepare_evidence_return(execution_receipt_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.evidence-return-receipt.v1",
        "packet": packet,
        "state": "returned_for_review",
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": packet["next_gate"],
    }


@app.get("/api/v1/operator/evidence-returns")
def operator_evidence_return_list(
    limit: int = 50,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    items = list_evidence_returns(limit)
    return {
        "schema": "vmi.evidence-return.v1",
        "items": items,
        "count": len(items),
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/evidence-returns/verify")
def operator_evidence_return_verify(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return verify_evidence_return_chain()


@app.get("/api/v1/operator/evidence-returns/{evidence_return_id}")
def operator_evidence_return_get(
    evidence_return_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    item = get_evidence_return(evidence_return_id, include_payload=True)
    if not item:
        raise base.HTTPException(status_code=404, detail="Evidence return packet not found.")
    return {
        "schema": "vmi.evidence-return.v1",
        "item": item,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
