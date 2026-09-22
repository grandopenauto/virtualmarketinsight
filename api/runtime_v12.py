from __future__ import annotations

from typing import Any

import api.runtime as previous
from api.execution_review import (
    CONTRACT_REGISTRY,
    ExecutionReviewInput,
    get_execution_review_manifest,
    list_execution_review_manifests,
    prepare_execution_review_manifest,
    verify_execution_review_chain,
)

previous.base.VERSION = "0.12.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/execution-reviews/schema")
def operator_execution_review_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.execution-review-manifest.v1",
        "purpose": "Resolve a latest human-authorized bounded action into a capability-specific execution proposal without dispatching or executing it.",
        "capability_contracts": [
            {
                "capability_id": item["capability_id"],
                "contract_id": item["contract_id"],
                "effect_class": item["effect_class"],
                "allowed_action_kinds": sorted(item["allowed_action_kinds"]),
            }
            for item in CONTRACT_REGISTRY.values()
        ],
        "authorization_must_be_latest": True,
        "append_only": True,
        "approval_scope_required": "execution_review_only",
        "execution_permitted_by_manifest": False,
        "dispatch_permitted_by_manifest": False,
        "execute_endpoint_exists": False,
        "dispatch_endpoint_exists": False,
        "external_actions_executed": 0,
    }


@app.post("/api/v1/operator/authorizations/{authorization_id}/execution-review/prepare")
def operator_prepare_execution_review(
    authorization_id: str,
    request: ExecutionReviewInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        manifest = prepare_execution_review_manifest(authorization_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.execution-review-manifest-receipt.v1",
        "manifest": manifest,
        "state": "execution_review_prepared",
        "approval_recorded": True,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": manifest["next_gate"],
    }


@app.get("/api/v1/operator/execution-reviews")
def operator_execution_review_list(
    limit: int = 50,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    items = list_execution_review_manifests(limit)
    return {
        "schema": "vmi.execution-review-manifest.v1",
        "items": items,
        "count": len(items),
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/execution-reviews/verify")
def operator_execution_review_verify(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return verify_execution_review_chain()


@app.get("/api/v1/operator/execution-reviews/{manifest_id}")
def operator_execution_review_get(
    manifest_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    item = get_execution_review_manifest(manifest_id, include_payload=True)
    if not item:
        raise base.HTTPException(status_code=404, detail="Execution review manifest not found.")
    return {
        "schema": "vmi.execution-review-manifest.v1",
        "item": item,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
