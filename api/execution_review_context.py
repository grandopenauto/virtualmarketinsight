from __future__ import annotations

import sqlite3
from typing import Any

from api.execution_review import CONTRACT_REGISTRY
from api.lineage_guard import assert_action_packet_current, assert_review_record_current
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_execution_review_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        action = conn.execute(
            """
            SELECT action_packet_id,record_id,event_id,created_at,action_kind,
                   objective,scope,target_capability,state,sequence
            FROM bounded_action_packets
            WHERE record_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if not action:
            return {
                "schema": "vmi.execution-review-context.v1",
                "record_id": record_id,
                "ready": False,
                "reason": "bounded_action_required",
                "execution_permitted": False,
                "dispatch_permitted": False,
                "external_actions_executed": 0,
            }
        action_item = dict(action)
        authorization = conn.execute(
            """
            SELECT authorization_id,action_packet_id,created_at,decision,
                   scope_confirmed,state,sequence
            FROM authorization_records
            WHERE action_packet_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (action_item["action_packet_id"],),
        ).fetchone()

    assert_action_packet_current(str(action_item["action_packet_id"]))
    auth_item = dict(authorization) if authorization else None
    if not auth_item:
        return {
            "schema": "vmi.execution-review-context.v1",
            "record_id": record_id,
            "action_packet_id": action_item["action_packet_id"],
            "ready": False,
            "reason": "human_authorization_required",
            "latest_authorization": None,
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }
    if auth_item.get("decision") != "approve_for_execution_review":
        return {
            "schema": "vmi.execution-review-context.v1",
            "record_id": record_id,
            "action_packet_id": action_item["action_packet_id"],
            "ready": False,
            "reason": "latest_human_disposition_does_not_approve_execution_review",
            "latest_authorization": auth_item,
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }

    target = str(action_item.get("target_capability") or "").strip().lower()
    contract = CONTRACT_REGISTRY.get(target)
    if not contract:
        return {
            "schema": "vmi.execution-review-context.v1",
            "record_id": record_id,
            "action_packet_id": action_item["action_packet_id"],
            "authorization_id": auth_item["authorization_id"],
            "ready": False,
            "reason": "target_capability_contract_not_allowlisted",
            "target_capability": action_item.get("target_capability"),
            "allowlisted_targets": sorted(CONTRACT_REGISTRY.keys()),
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }
    if action_item["action_kind"] not in contract["allowed_action_kinds"]:
        return {
            "schema": "vmi.execution-review-context.v1",
            "record_id": record_id,
            "action_packet_id": action_item["action_packet_id"],
            "authorization_id": auth_item["authorization_id"],
            "ready": False,
            "reason": "action_kind_not_allowed_by_capability_contract",
            "target_capability": action_item.get("target_capability"),
            "action_kind": action_item["action_kind"],
            "allowed_action_kinds": sorted(contract["allowed_action_kinds"]),
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }

    return {
        "schema": "vmi.execution-review-context.v1",
        "record_id": record_id,
        "action_packet_id": action_item["action_packet_id"],
        "authorization_id": auth_item["authorization_id"],
        "ready": True,
        "reason": None,
        "action": {
            "action_kind": action_item["action_kind"],
            "objective": action_item["objective"],
            "scope": action_item["scope"],
            "target_capability": action_item["target_capability"],
        },
        "proposed_contract": {
            "capability_id": contract["capability_id"],
            "contract_id": contract["contract_id"],
            "transport": contract["transport"],
            "effect_class": contract["effect_class"],
            "operations": contract["operations"],
        },
        "next_gate": "Prepare an execution-review manifest. That manifest still cannot execute or dispatch anything.",
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
    }
