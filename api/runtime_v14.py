from __future__ import annotations

from typing import Any

import api.runtime_v13 as previous
from api.dispatch_tickets import (
    DISPATCHABLE_CONTRACTS,
    DispatchTicketInput,
    get_dispatch_ticket,
    list_dispatch_tickets,
    prepare_dispatch_ticket,
    verify_dispatch_ticket_chain,
)

previous.base.VERSION = "0.14.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/dispatch-tickets/schema")
def operator_dispatch_ticket_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.dispatch-ticket.v1",
        "purpose": "Freeze one exact allowlisted read-only operation into a short-lived, single-use dispatch ticket without executing it.",
        "dispatchable_contracts": {
            contract: sorted(ops) for contract, ops in DISPATCHABLE_CONTRACTS.items()
        },
        "single_use": True,
        "ticket_ttl_minutes": {"min": 1, "max": 5, "default": 3},
        "revalidation_required_at_run": True,
        "execute_endpoint_exists": False,
        "run_endpoint_exists": False,
        "external_actions_executed": 0,
    }


@app.post("/api/v1/operator/execution-authorizations/{execution_authorization_id}/dispatch-ticket/prepare")
def operator_prepare_dispatch_ticket(
    execution_authorization_id: str,
    request: DispatchTicketInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        ticket = prepare_dispatch_ticket(execution_authorization_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.dispatch-ticket-receipt.v1",
        "ticket": ticket,
        "state": "prepared_not_dispatched",
        "dispatch_ready": True,
        "dispatch_executed": False,
        "external_actions_executed": 0,
        "next_gate": ticket["next_gate"],
    }


@app.get("/api/v1/operator/dispatch-tickets")
def operator_dispatch_ticket_list(
    limit: int = 50,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    items = list_dispatch_tickets(limit)
    return {
        "schema": "vmi.dispatch-ticket.v1",
        "items": items,
        "count": len(items),
        "dispatch_execution_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/dispatch-tickets/verify")
def operator_dispatch_ticket_verify(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return verify_dispatch_ticket_chain()


@app.get("/api/v1/operator/dispatch-tickets/{dispatch_ticket_id}")
def operator_dispatch_ticket_get(
    dispatch_ticket_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    item = get_dispatch_ticket(dispatch_ticket_id, include_payload=True)
    if not item:
        raise base.HTTPException(status_code=404, detail="Dispatch ticket not found.")
    return {
        "schema": "vmi.dispatch-ticket.v1",
        "item": item,
        "dispatch_execution_authority": False,
        "external_actions_executed": 0,
    }
