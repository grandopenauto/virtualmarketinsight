from __future__ import annotations

from typing import Any

import api.runtime_v14 as previous
from api.read_only_runner import (
    get_execution_receipt,
    list_execution_receipts,
    run_dispatch_ticket,
    verify_execution_receipt_chain,
)

previous.base.VERSION = "0.15.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/read-only-runner/schema")
def operator_read_only_runner_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.read-only-execution-receipt.v1",
        "purpose": "Consume one valid short-lived dispatch ticket exactly once and perform one fixed internal read-only operation.",
        "supported_capability": "opportunity-intelligence",
        "supported_contract": "oie.read-research.v1",
        "single_use_ticket": True,
        "claim_before_call": True,
        "arbitrary_paths_allowed": False,
        "external_writes_allowed": False,
        "capital_movement_allowed": False,
        "trading_allowed": False,
        "outreach_allowed": False,
        "external_actions_executed_by_runner": 0,
    }


@app.post("/api/v1/operator/dispatch-tickets/{dispatch_ticket_id}/run-read-only")
def operator_run_read_only_dispatch_ticket(
    dispatch_ticket_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        receipt = run_dispatch_ticket(dispatch_ticket_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.read-only-execution-receipt.v1",
        "receipt": receipt,
        "status": receipt["status"],
        "internal_read_actions_executed": receipt["internal_read_actions_executed"],
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/read-only-executions")
def operator_read_only_execution_list(
    limit: int = 50,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    items = list_execution_receipts(limit)
    return {
        "schema": "vmi.read-only-execution-receipt.v1",
        "items": items,
        "count": len(items),
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/read-only-executions/verify")
def operator_read_only_execution_verify(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return verify_execution_receipt_chain()


@app.get("/api/v1/operator/read-only-executions/{execution_receipt_id}")
def operator_read_only_execution_get(
    execution_receipt_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    item = get_execution_receipt(execution_receipt_id, include_result=True)
    if not item:
        raise base.HTTPException(status_code=404, detail="Read-only execution receipt not found.")
    return {
        "schema": "vmi.read-only-execution-receipt.v1",
        "item": item,
        "external_actions_executed": 0,
    }
