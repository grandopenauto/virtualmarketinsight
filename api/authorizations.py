from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from api.bounded_actions import get_bounded_action
from api.review_ledger import ledger_path

SCHEMA = "vmi.authorization-record.v1"
AuthorizationDecision = Literal[
    "approve_for_execution_review",
    "request_changes",
    "hold",
    "reject",
]


class AuthorizationInput(BaseModel):
    decision: AuthorizationDecision
    reviewer_label: str = Field(default="operator", max_length=120)
    rationale: str = Field(default="", max_length=1600)
    scope_confirmed: bool = False


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS authorization_records (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            authorization_id TEXT NOT NULL UNIQUE,
            action_packet_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer_label TEXT NOT NULL,
            rationale TEXT NOT NULL,
            scope_confirmed INTEGER NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_authorization_receipt_sha256 TEXT,
            authorization_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_authorizations_packet ON authorization_records(action_packet_id, sequence)"
    )
    return conn


def append_authorization(action_packet_id: str, request: AuthorizationInput) -> dict[str, Any]:
    packet = get_bounded_action(action_packet_id, include_payload=True)
    if not packet:
        raise KeyError("bounded_action_packet_not_found")

    if request.decision == "approve_for_execution_review":
        if not request.scope_confirmed:
            raise ValueError("scope_confirmation_required")
        if not request.rationale.strip():
            raise ValueError("approval_rationale_required")

    authorization_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    approval_recorded = request.decision == "approve_for_execution_review"
    state = {
        "approve_for_execution_review": "approved_for_execution_review_only",
        "request_changes": "changes_requested",
        "hold": "held",
        "reject": "rejected",
    }[request.decision]

    payload = {
        "schema": SCHEMA,
        "authorization_id": authorization_id,
        "action_packet_id": action_packet_id,
        "action_packet_receipt_sha256": packet.get("packet_receipt_sha256"),
        "decision": request.decision,
        "reviewer_label": request.reviewer_label.strip() or "operator",
        "rationale": request.rationale,
        "scope_confirmed": bool(request.scope_confirmed),
        "state": state,
        "authority": {
            "approval_recorded": approval_recorded,
            "approval_scope": "execution_review_only" if approval_recorded else "none",
            "execution_permitted": False,
            "dispatch_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "self_approval_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": (
            "Separate capability-specific execution review and explicit execution authorization. "
            "This authorization record does not execute or dispatch anything."
            if approval_recorded
            else "No execution review is authorized by this disposition."
        ),
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT authorization_receipt_sha256 FROM authorization_records ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["authorization_receipt_sha256"] if previous else ""
        receipt_material = {
            "schema": SCHEMA,
            "authorization_id": authorization_id,
            "action_packet_id": action_packet_id,
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_authorization_receipt_sha256": previous_receipt,
        }
        authorization_receipt = _sha256(receipt_material)
        conn.execute(
            """
            INSERT INTO authorization_records (
                authorization_id, action_packet_id, created_at, decision,
                reviewer_label, rationale, scope_confirmed, state, payload_json,
                payload_sha256, previous_authorization_receipt_sha256,
                authorization_receipt_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                authorization_id,
                action_packet_id,
                created_at,
                request.decision,
                payload["reviewer_label"],
                request.rationale,
                1 if request.scope_confirmed else 0,
                state,
                _canonical(payload),
                payload_sha,
                previous_receipt,
                authorization_receipt,
            ),
        )

    return {
        "schema": SCHEMA,
        "authorization_id": authorization_id,
        "action_packet_id": action_packet_id,
        "created_at": created_at,
        "decision": request.decision,
        "state": state,
        "payload_sha256": payload_sha,
        "previous_authorization_receipt_sha256": previous_receipt or None,
        "authorization_receipt_sha256": authorization_receipt,
        "approval_recorded": approval_recorded,
        "approval_scope": "execution_review_only" if approval_recorded else "none",
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def list_authorizations(action_packet_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not get_bounded_action(action_packet_id, include_payload=False):
        raise KeyError("bounded_action_packet_not_found")
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, authorization_id, action_packet_id, created_at,
                   decision, reviewer_label, rationale, scope_confirmed, state,
                   payload_sha256, previous_authorization_receipt_sha256,
                   authorization_receipt_sha256
            FROM authorization_records
            WHERE action_packet_id = ?
            ORDER BY sequence ASC
            LIMIT ?
            """,
            (action_packet_id, safe_limit),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_authorization_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM authorization_records ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_authorization_id": row["authorization_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_authorization_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_authorization_id": row["authorization_id"], "reason": "previous_authorization_receipt_mismatch"}
        receipt_material = {
            "schema": SCHEMA,
            "authorization_id": row["authorization_id"],
            "action_packet_id": row["action_packet_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_authorization_receipt_sha256": previous_receipt,
        }
        if _sha256(receipt_material) != row["authorization_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_authorization_id": row["authorization_id"], "reason": "authorization_receipt_hash_mismatch"}
        previous_receipt = row["authorization_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_authorization_receipt_sha256": previous_receipt or None,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
