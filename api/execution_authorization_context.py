from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from api.lineage_guard import assert_execution_review_manifest_current, assert_review_record_current
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_execution_authorization_context(record_id: str) -> dict[str, Any]:
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
                "schema": "vmi.execution-authorization-context.v1",
                "record_id": record_id,
                "ready": False,
                "reason": "execution_review_manifest_required",
                "execution_permitted": False,
                "dispatch_permitted": False,
                "external_actions_executed": 0,
            }
        manifest_item = dict(manifest)
        latest_exec_auth = conn.execute(
            """
            SELECT execution_authorization_id,manifest_id,created_at,expires_at,
                   decision,state,sequence
            FROM execution_authorizations
            WHERE manifest_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (manifest_item["manifest_id"],),
        ).fetchone()
        latest_packet_auth = conn.execute(
            """
            SELECT authorization_id,action_packet_id,decision,state,sequence
            FROM authorization_records
            WHERE action_packet_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (manifest_item["action_packet_id"],),
        ).fetchone()

    assert_execution_review_manifest_current(str(manifest_item["manifest_id"]))
    manifest_payload = json.loads(manifest_item["payload_json"])
    proposed = manifest_payload.get("proposed_execution", {}) or {}
    packet_auth = dict(latest_packet_auth) if latest_packet_auth else None
    if not packet_auth or packet_auth.get("authorization_id") != manifest_item.get("authorization_id"):
        return {
            "schema": "vmi.execution-authorization-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "ready": False,
            "reason": "manifest_source_authorization_is_stale",
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }
    if packet_auth.get("decision") != "approve_for_execution_review":
        return {
            "schema": "vmi.execution-authorization-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "ready": False,
            "reason": "current_packet_authorization_blocks_execution_review",
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }
    if proposed.get("effect_class") != "read_only_internal":
        return {
            "schema": "vmi.execution-authorization-context.v1",
            "record_id": record_id,
            "manifest_id": manifest_item["manifest_id"],
            "ready": False,
            "reason": "only_read_only_internal_effect_class_supported",
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_actions_executed": 0,
        }

    prior = dict(latest_exec_auth) if latest_exec_auth else None
    if prior and prior.get("expires_at"):
        try:
            prior["expired"] = datetime.now(timezone.utc) >= datetime.fromisoformat(str(prior["expires_at"]))
        except ValueError:
            prior["expired"] = None

    return {
        "schema": "vmi.execution-authorization-context.v1",
        "record_id": record_id,
        "manifest_id": manifest_item["manifest_id"],
        "manifest_state": manifest_item["state"],
        "ready": True,
        "reason": None,
        "proposed_execution": {
            "capability_id": proposed.get("capability_id"),
            "contract_id": proposed.get("contract_id"),
            "effect_class": proposed.get("effect_class"),
            "action_kind": proposed.get("action_kind"),
            "objective": proposed.get("objective"),
            "scope": proposed.get("scope"),
            "operations": proposed.get("operations", []),
        },
        "permitted_effects": manifest_payload.get("permitted_effects", []),
        "prohibited_effects": manifest_payload.get("prohibited_effects", []),
        "required_confirmations": [
            "scope_confirmed",
            "effects_confirmed",
            "capability_health_confirmed",
            "rationale",
        ],
        "ttl_minutes": {"min": 1, "max": 60, "default": 15},
        "latest_execution_authorization": prior,
        "next_gate": "Explicit human final authorization for this exact read-only manifest. Authorization still does not dispatch.",
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
    }
