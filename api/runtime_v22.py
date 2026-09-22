from __future__ import annotations

import sqlite3
from typing import Any

import api.runtime_v21 as previous
from api.authorizations import AuthorizationInput, append_authorization
from api.bounded_actions import BoundedActionInput, prepare_bounded_action
from api.execution_authorizations import ExecutionAuthorizationInput, append_execution_authorization
from api.execution_review import ExecutionReviewInput, get_execution_review_manifest, prepare_execution_review_manifest
from api.lineage_guard import assert_action_packet_current, assert_review_event_current, assert_review_record_current
from api.review_events import ReviewEventInput, append_review_event
from api.review_ledger import ledger_path

previous.base.VERSION = "0.22.0"
app = previous.app
base = previous.base

_REVIEW_EVENT_PATH = "/api/v1/operator/review-ledger/{record_id}/events"
_BOUNDED_ACTION_PATH = "/api/v1/operator/review-events/{event_id}/bounded-action/prepare"
_AUTH_PATH = "/api/v1/operator/bounded-actions/{action_packet_id}/authorizations"
_EXEC_REVIEW_PATH = "/api/v1/operator/authorizations/{authorization_id}/execution-review/prepare"
_EXEC_AUTH_PATH = "/api/v1/operator/execution-reviews/{manifest_id}/authorize"
_MUTATION_PATHS = {_REVIEW_EVENT_PATH, _BOUNDED_ACTION_PATH, _AUTH_PATH, _EXEC_REVIEW_PATH, _EXEC_AUTH_PATH}

app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) in _MUTATION_PATHS
        and "POST" in getattr(route, "methods", set())
    )
]


def _authorization_action_packet_id(authorization_id: str) -> str:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT action_packet_id FROM authorization_records WHERE authorization_id = ? LIMIT 1",
            (authorization_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise KeyError("authorization_not_found")
    return str(row["action_packet_id"])


@app.get("/api/v1/operator/lineage-guard/enforcement")
def operator_lineage_guard_enforcement(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.lineage-freshness-guard.v2",
        "enforced_mutation_gates": [
            "review_event_append",
            "bounded_action_prepare",
            "human_authorization_append",
            "execution_review_prepare",
            "execution_authorization_append",
            "dispatch_ticket_prepare",
            "read_only_runner",
        ],
        "stale_event_reuse_permitted": False,
        "superseded_cycle_reuse_permitted": False,
        "historical_artifacts_remain_readable": True,
        "external_actions_executed": 0,
    }


@app.post(_REVIEW_EVENT_PATH)
def operator_append_review_event_v22(
    record_id: str,
    event: ReviewEventInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        assert_review_record_current(record_id)
        receipt = append_review_event(record_id, event)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.review-event-receipt.v1",
        "event": receipt,
        "state": "review_recorded_no_authority",
        "lineage_freshness_verified": True,
        "approval_recorded": False,
        "execution_permitted": False,
        "external_actions_executed": 0,
        "next_gate": receipt["next_gate"],
    }


@app.post(_BOUNDED_ACTION_PATH)
def operator_prepare_bounded_action_v22(
    event_id: str,
    request: BoundedActionInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        assert_review_event_current(event_id)
        packet = prepare_bounded_action(event_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.bounded-action-receipt.v1",
        "packet": packet,
        "state": "prepared_not_approved",
        "lineage_freshness_verified": True,
        "approval_recorded": False,
        "execution_permitted": False,
        "external_actions_executed": 0,
        "next_gate": packet["next_gate"],
    }


@app.post(_AUTH_PATH)
def operator_append_authorization_v22(
    action_packet_id: str,
    request: AuthorizationInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        assert_action_packet_current(action_packet_id)
        receipt = append_authorization(action_packet_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.authorization-receipt.v1",
        "authorization": receipt,
        "lineage_freshness_verified": True,
        "approval_recorded": receipt["approval_recorded"],
        "approval_scope": receipt["approval_scope"],
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": receipt["next_gate"],
    }


@app.post(_EXEC_REVIEW_PATH)
def operator_prepare_execution_review_v22(
    authorization_id: str,
    request: ExecutionReviewInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        action_packet_id = _authorization_action_packet_id(authorization_id)
        assert_action_packet_current(action_packet_id)
        manifest = prepare_execution_review_manifest(authorization_id, request)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.execution-review-manifest-receipt.v1",
        "manifest": manifest,
        "state": "execution_review_prepared",
        "lineage_freshness_verified": True,
        "approval_recorded": True,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": manifest["next_gate"],
    }


@app.post(_EXEC_AUTH_PATH)
def operator_record_execution_authorization_v22(
    manifest_id: str,
    request: ExecutionAuthorizationInput,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        manifest = get_execution_review_manifest(manifest_id, include_payload=False)
        if not manifest:
            raise KeyError("execution_review_manifest_not_found")
        assert_action_packet_current(manifest["action_packet_id"])
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
