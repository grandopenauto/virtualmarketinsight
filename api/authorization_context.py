from __future__ import annotations

import sqlite3
from typing import Any

from api.bounded_actions import get_bounded_action
from api.lineage_guard import assert_action_packet_current, assert_review_record_current
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_authorization_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        row = conn.execute(
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
        if not row:
            return {
                "schema": "vmi.operator-authorization-context.v1",
                "record_id": record_id,
                "current_action": None,
                "latest_authorization": None,
                "can_record_authorization": False,
                "reason": "bounded_action_required",
                "approval_scope": "execution_review_only",
                "execution_permitted": False,
                "dispatch_permitted": False,
                "external_actions_executed": 0,
            }
        action = dict(row)
        latest_auth = conn.execute(
            """
            SELECT authorization_id,action_packet_id,created_at,decision,
                   scope_confirmed,state,sequence
            FROM authorization_records
            WHERE action_packet_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (action["action_packet_id"],),
        ).fetchone()

    assert_action_packet_current(str(action["action_packet_id"]))
    full = get_bounded_action(str(action["action_packet_id"]), include_payload=True)
    payload = (full or {}).get("payload", {}) or {}
    return {
        "schema": "vmi.operator-authorization-context.v1",
        "record_id": record_id,
        "current_action": {
            "action_packet_id": action["action_packet_id"],
            "event_id": action["event_id"],
            "created_at": action["created_at"],
            "action_kind": action["action_kind"],
            "objective": action["objective"],
            "scope": action["scope"],
            "target_capability": action["target_capability"],
            "state": action["state"],
            "allowed_effects": payload.get("allowed_effects", []),
            "prohibited_effects": payload.get("prohibited_effects", []),
            "preconditions": payload.get("preconditions", []),
        },
        "latest_authorization": dict(latest_auth) if latest_auth else None,
        "decisions": [
            "approve_for_execution_review",
            "request_changes",
            "hold",
            "reject",
        ],
        "can_record_authorization": True,
        "approval_scope": "execution_review_only",
        "approve_requires": ["scope_confirmed", "rationale"],
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
    }
