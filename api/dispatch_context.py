from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from api.dispatch_tickets import DISPATCHABLE_CONTRACTS
from api.lineage_guard import assert_execution_review_manifest_current, assert_review_record_current
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_dispatch_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        manifest = conn.execute(
            """
            SELECT m.* FROM execution_review_manifests m
            JOIN bounded_action_packets a ON a.action_packet_id = m.action_packet_id
            WHERE a.record_id = ?
            ORDER BY m.sequence DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if not manifest:
            return {
                "schema": "vmi.dispatch-context.v1",
                "record_id": record_id,
                "ready": False,
                "reason": "execution_review_manifest_required",
                "dispatch_permitted": False,
                "external_actions_executed": 0,
            }
        manifest_item = dict(manifest)
        execution_auth = conn.execute(
            """
            SELECT execution_authorization_id,manifest_id,action_packet_id,
                   created_at,expires_at,decision,state,sequence
            FROM execution_authorizations
            WHERE manifest_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (manifest_item["manifest_id"],),
        ).fetchone()

    assert_execution_review_manifest_current(str(manifest_item["manifest_id"]))
    if not execution_auth:
        return {
            "schema": "vmi.dispatch-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "ready": False,
            "reason": "final_execution_authorization_required",
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }
    auth = dict(execution_auth)
    if auth.get("decision") != "authorize_read_only_execution":
        return {
            "schema": "vmi.dispatch-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "execution_authorization_id": auth.get("execution_authorization_id"),
            "ready": False,
            "reason": "latest_final_disposition_does_not_authorize_read_only_execution",
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }
    try:
        expires_at = datetime.fromisoformat(str(auth["expires_at"]))
    except (TypeError, ValueError):
        return {
            "schema": "vmi.dispatch-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "execution_authorization_id": auth.get("execution_authorization_id"),
            "ready": False,
            "reason": "execution_authorization_expiry_invalid",
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }
    now = datetime.now(timezone.utc)
    if now >= expires_at:
        return {
            "schema": "vmi.dispatch-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "execution_authorization_id": auth.get("execution_authorization_id"),
            "ready": False,
            "reason": "execution_authorization_expired",
            "expires_at": auth.get("expires_at"),
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }

    manifest_payload = json.loads(manifest_item["payload_json"])
    proposed = manifest_payload.get("proposed_execution", {}) or {}
    contract_id = str(proposed.get("contract_id") or "")
    allowed_operations = sorted(DISPATCHABLE_CONTRACTS.get(contract_id, set()))
    if not allowed_operations:
        return {
            "schema": "vmi.dispatch-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "execution_authorization_id": auth.get("execution_authorization_id"),
            "ready": False,
            "reason": "contract_not_dispatchable_by_current_runner",
            "contract_id": contract_id,
            "capability_id": proposed.get("capability_id"),
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }

    remaining = max(0, int((expires_at - now).total_seconds()))
    return {
        "schema": "vmi.dispatch-context.v1",
        "record_id": record_id,
        "manifest_id": manifest_item["manifest_id"],
        "execution_authorization_id": auth["execution_authorization_id"],
        "ready": True,
        "reason": None,
        "authorization_expires_at": auth["expires_at"],
        "authorization_remaining_seconds": remaining,
        "dispatch_contract": {
            "capability_id": proposed.get("capability_id"),
            "contract_id": contract_id,
            "effect_class": proposed.get("effect_class"),
            "allowed_operations": allowed_operations,
        },
        "ticket": {
            "single_use": True,
            "ttl_minutes": {"min": 1, "max": 5, "default": 3},
            "limit": {"min": 1, "max": 20, "default": 5},
            "expires_no_later_than_authorization": True,
        },
        "next_gate": "Prepare one short-lived single-use dispatch ticket. Preparing a ticket still does not execute it.",
        "dispatch_permitted": False,
        "external_actions_executed": 0,
    }
