from __future__ import annotations

from typing import Any

import api.runtime_v20 as previous
from api.dispatch_tickets import DispatchTicketInput, get_dispatch_ticket, prepare_dispatch_ticket
from api.execution_authorizations import get_execution_authorization
from api.execution_review import get_execution_review_manifest
from api.lineage_guard import assert_action_packet_current, inspect_action_packet_freshness
from api.read_only_runner import run_dispatch_ticket

previous.base.VERSION = "0.21.0"
app = previous.app
base = previous.base

_PREPARE_PATH = "/api/v1/operator/execution-authorizations/{execution_authorization_id}/dispatch-ticket/prepare"
_RUN_PATH = "/api/v1/operator/dispatch-tickets/{dispatch_ticket_id}/run-read-only"

app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) in {_PREPARE_PATH, _RUN_PATH}
        and "POST" in getattr(route, "methods", set())
    )
]


def _assert_execution_authorization_lineage_current(execution_authorization_id: str) -> str:
    execution_auth = get_execution_authorization(execution_authorization_id, include_payload=False)
    if not execution_auth:
        raise KeyError("execution_authorization_not_found")
    manifest = get_execution_review_manifest(execution_auth["manifest_id"], include_payload=False)
    if not manifest:
        raise KeyError("execution_review_manifest_not_found")
    assert_action_packet_current(manifest["action_packet_id"])
    return manifest["action_packet_id"]


@app.get("/api/v1/operator/lineage-guard/schema")
def operator_lineage_guard_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.lineage-freshness-guard.v1",
        "purpose": "Prevent stale review events or superseded review cycles from crossing active dispatch or execution chokepoints.",
        "checks": [
            "source review event is latest for its review record",
            "source review record has not been superseded by a successor review cycle",
        ],
        "enforced_at": ["dispatch_ticket_prepare", "read_only_runner"],
        "historical_artifacts_remain_readable": True,
        "approval_authority": False,
        "execution_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/lineage-guard/action-packets/{action_packet_id}")
def operator_lineage_guard_action_packet(
    action_packet_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return inspect_action_packet_freshness(action_packet_id)


@app.post(_PREPARE_PATH)
def operator_prepare_dispatch_ticket_v21(
    execution_authorization_id: str,
    request: DispatchTicketInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        _assert_execution_authorization_lineage_current(execution_authorization_id)
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
def operator_run_read_only_dispatch_ticket_v21(
    dispatch_ticket_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        ticket = get_dispatch_ticket(dispatch_ticket_id, include_payload=False)
        if not ticket:
            raise KeyError("dispatch_ticket_not_found")
        assert_action_packet_current(ticket["action_packet_id"])
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
