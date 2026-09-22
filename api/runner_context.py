from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from api.dispatch_tickets import get_dispatch_ticket
from api.execution_authorizations import get_execution_authorization
from api.lineage_guard import assert_dispatch_ticket_current, assert_review_record_current
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_runner_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        ticket = conn.execute(
            """
            SELECT t.* FROM dispatch_tickets t
            JOIN bounded_action_packets a ON a.action_packet_id = t.action_packet_id
            WHERE a.record_id = ?
            ORDER BY t.sequence DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if not ticket:
            return {
                "schema": "vmi.runner-context.v1",
                "record_id": record_id,
                "ready": False,
                "reason": "dispatch_ticket_required",
                "external_actions_executed": 0,
            }
        ticket_item = dict(ticket)
        try:
            claim = conn.execute(
                "SELECT claim_id,dispatch_ticket_id,claimed_at FROM dispatch_claims WHERE dispatch_ticket_id = ? LIMIT 1",
                (ticket_item["dispatch_ticket_id"],),
            ).fetchone()
        except sqlite3.OperationalError:
            claim = None

    assert_dispatch_ticket_current(str(ticket_item["dispatch_ticket_id"]))
    if claim:
        return {
            "schema": "vmi.runner-context.v1",
            "record_id": record_id,
            "dispatch_ticket_id": ticket_item["dispatch_ticket_id"],
            "ready": False,
            "reason": "dispatch_ticket_already_consumed",
            "claim": dict(claim),
            "external_actions_executed": 0,
        }

    now = datetime.now(timezone.utc)
    try:
        ticket_expiry = datetime.fromisoformat(str(ticket_item["expires_at"]))
    except (TypeError, ValueError):
        return {
            "schema": "vmi.runner-context.v1",
            "record_id": record_id,
            "dispatch_ticket_id": ticket_item["dispatch_ticket_id"],
            "ready": False,
            "reason": "dispatch_ticket_expiry_invalid",
            "external_actions_executed": 0,
        }
    if now >= ticket_expiry:
        return {
            "schema": "vmi.runner-context.v1",
            "record_id": record_id,
            "dispatch_ticket_id": ticket_item["dispatch_ticket_id"],
            "ready": False,
            "reason": "dispatch_ticket_expired",
            "expires_at": ticket_item.get("expires_at"),
            "external_actions_executed": 0,
        }

    authorization = get_execution_authorization(str(ticket_item["execution_authorization_id"]), include_payload=False)
    if not authorization:
        return {
            "schema": "vmi.runner-context.v1",
            "record_id": record_id,
            "dispatch_ticket_id": ticket_item["dispatch_ticket_id"],
            "ready": False,
            "reason": "execution_authorization_not_found",
            "external_actions_executed": 0,
        }
    try:
        auth_expiry = datetime.fromisoformat(str(authorization["expires_at"]))
    except (TypeError, ValueError):
        auth_expiry = now
    if authorization.get("decision") != "authorize_read_only_execution" or now >= auth_expiry:
        return {
            "schema": "vmi.runner-context.v1",
            "record_id": record_id,
            "dispatch_ticket_id": ticket_item["dispatch_ticket_id"],
            "ready": False,
            "reason": "execution_authorization_not_current_and_unexpired",
            "external_actions_executed": 0,
        }

    ticket_full = get_dispatch_ticket(str(ticket_item["dispatch_ticket_id"]), include_payload=True)
    plan = (ticket_full or {}).get("payload", {}).get("dispatch_plan", {}) or {}
    remaining = max(0, int((ticket_expiry - now).total_seconds()))
    return {
        "schema": "vmi.runner-context.v1",
        "record_id": record_id,
        "dispatch_ticket_id": ticket_item["dispatch_ticket_id"],
        "execution_authorization_id": ticket_item["execution_authorization_id"],
        "manifest_id": ticket_item["manifest_id"],
        "ready": True,
        "reason": None,
        "ticket_remaining_seconds": remaining,
        "single_use": True,
        "dispatch_plan": {
            "capability_id": plan.get("capability_id"),
            "contract_id": plan.get("contract_id"),
            "effect_class": plan.get("effect_class"),
            "operation": plan.get("operation"),
            "parameters": plan.get("parameters", {}),
            "purpose": plan.get("purpose"),
        },
        "runner": {
            "claim_before_call": True,
            "external_writes_allowed": False,
            "capital_movement_allowed": False,
            "trading_allowed": False,
            "outreach_allowed": False,
            "credential_changes_allowed": False,
        },
        "next_gate": "Explicit operator run command. The runner will revalidate ticket freshness, expiry, authorization, allowlist, and live capability health before one read-only call.",
        "internal_read_actions_executed": 0,
        "external_actions_executed": 0,
    }
