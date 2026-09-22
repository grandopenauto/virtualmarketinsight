from __future__ import annotations

from typing import Any

import api.runtime_v30 as previous
from api.dispatch_tickets import DispatchTicketInput, get_dispatch_ticket, prepare_dispatch_ticket
from api.execution_authorizations import (
    ExecutionAuthorizationInput,
    append_execution_authorization,
    get_execution_authorization,
)
from api.lineage_guard import assert_execution_review_manifest_current
from api.read_only_runner import run_dispatch_ticket

previous.base.VERSION = "0.31.0"
app = previous.app
base = previous.base

_EXEC_AUTH_PATH = "/api/v1/operator/execution-reviews/{manifest_id}/authorize"
_DISPATCH_PREP_PATH = "/api/v1/operator/execution-authorizations/{execution_authorization_id}/dispatch-ticket/prepare"
_RUN_PATH = "/api/v1/operator/dispatch-tickets/{dispatch_ticket_id}/run-read-only"
_HARDENED = {_EXEC_AUTH_PATH, _DISPATCH_PREP_PATH, _RUN_PATH}

app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) in _HARDENED
        and "POST" in getattr(route, "methods", set())
    )
]


@app.get("/api/v1/operator/lineage-guard/execution-manifests/schema")
def operator_manifest_freshness_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.lineage-freshness-guard.v4",
        "manifest_must_be_latest_for_action_packet": True,
        "enforced_at": [
            "final_execution_authorization",
            "dispatch_ticket_preparation",
            "read_only_runner",
        ],
        "superseded_manifest_reuse_permitted": False,
        "historical_artifacts_remain_readable": True,
        "external_actions_executed": 0,
    }


@app.post(_EXEC_AUTH_PATH)
def operator_record_execution_authorization_v31(
    manifest_id: str,
    request: ExecutionAuthorizationInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        assert_execution_review_manifest_current(manifest_id)
        authorization = append_execution_authorization(manifest_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.execution-authorization-receipt.v1",
        "authorization": authorization,
        "state": authorization["state"],
        "lineage_freshness_verified": True,
        "execution_authorized": authorization["execution_authorized"],
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": authorization["next_gate"],
    }


@app.post(_DISPATCH_PREP_PATH)
def operator_prepare_dispatch_ticket_v31(
    execution_authorization_id: str,
    request: DispatchTicketInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        execution_auth = get_execution_authorization(execution_authorization_id, include_payload=False)
        if not execution_auth:
            raise KeyError("execution_authorization_not_found")
        assert_execution_review_manifest_current(str(execution_auth["manifest_id"]))
        ticket = prepare_dispatch_ticket(execution_authorization_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.dispatch-ticket-receipt.v1",
        "ticket": ticket,
        "state": "prepared_not_dispatched",
        "lineage_freshness_verified": True,
        "dispatch_ready": True,
        "dispatch_executed": False,
        "external_actions_executed": 0,
        "next_gate": ticket["next_gate"],
    }


@app.post(_RUN_PATH)
def operator_run_read_only_dispatch_ticket_v31(
    dispatch_ticket_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        ticket = get_dispatch_ticket(dispatch_ticket_id, include_payload=False)
        if not ticket:
            raise KeyError("dispatch_ticket_not_found")
        assert_execution_review_manifest_current(str(ticket["manifest_id"]))
        receipt = run_dispatch_ticket(dispatch_ticket_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.read-only-execution-receipt.v1",
        "receipt": receipt,
        "status": receipt["status"],
        "lineage_freshness_verified": True,
        "internal_read_actions_executed": receipt["internal_read_actions_executed"],
        "external_actions_executed": 0,
    }
