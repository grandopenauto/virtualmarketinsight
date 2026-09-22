from __future__ import annotations

from typing import Any

import api.runtime_v12 as previous
from api.execution_authorizations import (
    ExecutionAuthorizationInput,
    append_execution_authorization,
    get_execution_authorization,
    list_execution_authorizations,
    verify_execution_authorization_chain,
)

previous.base.VERSION = "0.13.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/execution-authorizations/schema")
def operator_execution_authorizations_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.execution-authorization.v1",
        "purpose": "Record a short-lived human authorization for an allowlisted read-only internal execution contract without dispatching it.",
        "decisions": [
            "authorize_read_only_execution",
            "request_changes",
            "hold",
            "reject",
        ],
        "effect_class_supported": "read_only_internal",
        "ttl_minutes": {"min": 1, "max": 60, "default": 15},
        "scope_confirmation_required": True,
        "effects_confirmation_required": True,
        "capability_health_confirmation_required": True,
        "dispatch_permitted_by_authorization": False,
        "execute_endpoint_exists": False,
        "dispatch_endpoint_exists": False,
        "external_actions_executed": 0,
    }


@app.post("/api/v1/operator/execution-reviews/{manifest_id}/authorize")
def operator_record_execution_authorization(
    manifest_id: str,
    request: ExecutionAuthorizationInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        authorization = append_execution_authorization(manifest_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.execution-authorization-receipt.v1",
        "authorization": authorization,
        "state": authorization["state"],
        "execution_authorized": authorization["execution_authorized"],
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": authorization["next_gate"],
    }


@app.get("/api/v1/operator/execution-authorizations")
def operator_execution_authorizations_list(
    limit: int = 50,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    items = list_execution_authorizations(limit)
    return {
        "schema": "vmi.execution-authorization.v1",
        "items": items,
        "count": len(items),
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/execution-authorizations/verify")
def operator_execution_authorizations_verify(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return verify_execution_authorization_chain()


@app.get("/api/v1/operator/execution-authorizations/{execution_authorization_id}")
def operator_execution_authorization_get(
    execution_authorization_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    item = get_execution_authorization(execution_authorization_id, include_payload=True)
    if not item:
        raise base.HTTPException(status_code=404, detail="Execution authorization not found.")
    return {
        "schema": "vmi.execution-authorization.v1",
        "item": item,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
