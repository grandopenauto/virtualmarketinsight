from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from api.execution_authorizations import get_execution_authorization
from api.execution_review import get_execution_review_manifest
from api.review_ledger import ledger_path

SCHEMA = "vmi.dispatch-ticket.v1"


class DispatchTicketInput(BaseModel):
    operation: str = Field(min_length=2, max_length=120)
    limit: int = Field(default=5, ge=1, le=20)
    purpose: str = Field(default="", max_length=1200)
    ttl_minutes: int = Field(default=3, ge=1, le=5)


DISPATCHABLE_CONTRACTS = {
    "oie.read-research.v1": {"opportunities", "demand_status", "demand_matches"},
}


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
        CREATE TABLE IF NOT EXISTS dispatch_tickets (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            dispatch_ticket_id TEXT NOT NULL UNIQUE,
            execution_authorization_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL,
            action_packet_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_dispatch_ticket_receipt_sha256 TEXT,
            dispatch_ticket_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dispatch_tickets_execauth ON dispatch_tickets(execution_authorization_id, sequence)"
    )
    return conn


def _latest_execution_authorization(manifest_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM execution_authorizations WHERE manifest_id = ? ORDER BY sequence DESC LIMIT 1",
            (manifest_id,),
        ).fetchone()
    return dict(row) if row else None


def _latest_packet_authorization(action_packet_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM authorization_records WHERE action_packet_id = ? ORDER BY sequence DESC LIMIT 1",
            (action_packet_id,),
        ).fetchone()
    return dict(row) if row else None


def prepare_dispatch_ticket(
    execution_authorization_id: str, request: DispatchTicketInput
) -> dict[str, Any]:
    execution_auth = get_execution_authorization(execution_authorization_id, include_payload=True)
    if not execution_auth:
        raise KeyError("execution_authorization_not_found")
    if execution_auth["decision"] != "authorize_read_only_execution":
        raise ValueError("execution_authorization_does_not_authorize_read_only_execution")

    now = datetime.now(timezone.utc)
    auth_expiry = datetime.fromisoformat(execution_auth["expires_at"])
    if now >= auth_expiry:
        raise ValueError("execution_authorization_expired")

    manifest = get_execution_review_manifest(execution_auth["manifest_id"], include_payload=True)
    if not manifest:
        raise KeyError("execution_review_manifest_not_found")

    latest_exec_auth = _latest_execution_authorization(manifest["manifest_id"])
    if not latest_exec_auth or latest_exec_auth["execution_authorization_id"] != execution_authorization_id:
        raise ValueError("execution_authorization_is_not_latest_for_manifest")

    latest_packet_auth = _latest_packet_authorization(manifest["action_packet_id"])
    if not latest_packet_auth or latest_packet_auth["authorization_id"] != manifest["authorization_id"]:
        raise ValueError("manifest_source_authorization_is_no_longer_latest")
    if latest_packet_auth["decision"] != "approve_for_execution_review":
        raise ValueError("current_packet_authorization_blocks_dispatch")

    proposed = manifest["payload"].get("proposed_execution", {})
    contract_id = proposed.get("contract_id", "")
    allowed_ops = DISPATCHABLE_CONTRACTS.get(contract_id)
    if not allowed_ops:
        raise ValueError("contract_not_dispatchable")
    if request.operation not in allowed_ops:
        raise ValueError("operation_not_allowlisted_for_contract")

    ticket_expiry = min(now + timedelta(minutes=request.ttl_minutes), auth_expiry)
    if ticket_expiry <= now:
        raise ValueError("dispatch_ticket_expiry_invalid")

    dispatch_ticket_id = str(uuid4())
    created_at = now.isoformat()
    expires_at = ticket_expiry.isoformat()
    payload = {
        "schema": SCHEMA,
        "dispatch_ticket_id": dispatch_ticket_id,
        "execution_authorization_id": execution_authorization_id,
        "execution_authorization_receipt_sha256": execution_auth.get("execution_authorization_receipt_sha256"),
        "manifest_id": manifest["manifest_id"],
        "manifest_receipt_sha256": manifest.get("manifest_receipt_sha256"),
        "action_packet_id": manifest["action_packet_id"],
        "created_at": created_at,
        "expires_at": expires_at,
        "state": "prepared_not_dispatched",
        "single_use": True,
        "dispatch_plan": {
            "capability_id": proposed.get("capability_id"),
            "contract_id": contract_id,
            "effect_class": "read_only_internal",
            "operation": request.operation,
            "parameters": {"limit": request.limit},
            "purpose": request.purpose,
        },
        "revalidation_required_at_run": [
            "ticket_not_expired",
            "ticket_not_previously_consumed",
            "execution_authorization_not_expired",
            "execution_authorization_still_latest",
            "packet_authorization_still_latest",
            "capability_health_live",
            "operation_still_allowlisted",
        ],
        "authority": {
            "read_only_execution_authorized": True,
            "dispatch_ready": True,
            "dispatch_executed": False,
            "external_write_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": "Single-use read-only runner revalidation. Preparing this ticket does not execute it.",
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT dispatch_ticket_receipt_sha256 FROM dispatch_tickets ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["dispatch_ticket_receipt_sha256"] if previous else ""
        material = {
            "schema": SCHEMA,
            "dispatch_ticket_id": dispatch_ticket_id,
            "execution_authorization_id": execution_authorization_id,
            "manifest_id": manifest["manifest_id"],
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_dispatch_ticket_receipt_sha256": previous_receipt,
        }
        receipt = _sha256(material)
        conn.execute(
            """
            INSERT INTO dispatch_tickets (
                dispatch_ticket_id, execution_authorization_id, manifest_id,
                action_packet_id, created_at, expires_at, capability_id,
                contract_id, operation, state, payload_json, payload_sha256,
                previous_dispatch_ticket_receipt_sha256,
                dispatch_ticket_receipt_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dispatch_ticket_id,
                execution_authorization_id,
                manifest["manifest_id"],
                manifest["action_packet_id"],
                created_at,
                expires_at,
                proposed.get("capability_id", ""),
                contract_id,
                request.operation,
                "prepared_not_dispatched",
                _canonical(payload),
                payload_sha,
                previous_receipt,
                receipt,
            ),
        )

    return {
        "schema": SCHEMA,
        "dispatch_ticket_id": dispatch_ticket_id,
        "execution_authorization_id": execution_authorization_id,
        "manifest_id": manifest["manifest_id"],
        "action_packet_id": manifest["action_packet_id"],
        "created_at": created_at,
        "expires_at": expires_at,
        "capability_id": proposed.get("capability_id"),
        "contract_id": contract_id,
        "operation": request.operation,
        "state": "prepared_not_dispatched",
        "payload_sha256": payload_sha,
        "previous_dispatch_ticket_receipt_sha256": previous_receipt or None,
        "dispatch_ticket_receipt_sha256": receipt,
        "dispatch_ready": True,
        "dispatch_executed": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def get_dispatch_ticket(dispatch_ticket_id: str, include_payload: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM dispatch_tickets WHERE dispatch_ticket_id = ? LIMIT 1",
            (dispatch_ticket_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def list_dispatch_tickets(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, dispatch_ticket_id, execution_authorization_id,
                   manifest_id, action_packet_id, created_at, expires_at,
                   capability_id, contract_id, operation, state, payload_sha256,
                   previous_dispatch_ticket_receipt_sha256,
                   dispatch_ticket_receipt_sha256
            FROM dispatch_tickets
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_dispatch_ticket_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM dispatch_tickets ORDER BY sequence ASC").fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_dispatch_ticket_id": row["dispatch_ticket_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_dispatch_ticket_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_dispatch_ticket_id": row["dispatch_ticket_id"], "reason": "previous_receipt_mismatch"}
        material = {
            "schema": SCHEMA,
            "dispatch_ticket_id": row["dispatch_ticket_id"],
            "execution_authorization_id": row["execution_authorization_id"],
            "manifest_id": row["manifest_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_dispatch_ticket_receipt_sha256": previous_receipt,
        }
        if _sha256(material) != row["dispatch_ticket_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_dispatch_ticket_id": row["dispatch_ticket_id"], "reason": "receipt_hash_mismatch"}
        previous_receipt = row["dispatch_ticket_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_dispatch_ticket_receipt_sha256": previous_receipt or None,
        "dispatch_execution_authority": False,
        "external_actions_executed": 0,
    }
