from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from api.execution_review import get_execution_review_manifest
from api.review_ledger import ledger_path

SCHEMA = "vmi.execution-authorization.v1"
ExecutionDecision = Literal[
    "authorize_read_only_execution",
    "request_changes",
    "hold",
    "reject",
]


class ExecutionAuthorizationInput(BaseModel):
    decision: ExecutionDecision
    reviewer_label: str = Field(default="operator", max_length=120)
    rationale: str = Field(default="", max_length=1600)
    scope_confirmed: bool = False
    effects_confirmed: bool = False
    capability_health_confirmed: bool = False
    ttl_minutes: int = Field(default=15, ge=1, le=60)


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
        CREATE TABLE IF NOT EXISTS execution_authorizations (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_authorization_id TEXT NOT NULL UNIQUE,
            manifest_id TEXT NOT NULL,
            action_packet_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            decision TEXT NOT NULL,
            reviewer_label TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_execution_authorization_receipt_sha256 TEXT,
            execution_authorization_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_execution_authorizations_manifest ON execution_authorizations(manifest_id, sequence)"
    )
    return conn


def _latest_packet_authorization(action_packet_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM authorization_records WHERE action_packet_id = ? ORDER BY sequence DESC LIMIT 1",
            (action_packet_id,),
        ).fetchone()
    return dict(row) if row else None


def append_execution_authorization(
    manifest_id: str, request: ExecutionAuthorizationInput
) -> dict[str, Any]:
    manifest = get_execution_review_manifest(manifest_id, include_payload=True)
    if not manifest:
        raise KeyError("execution_review_manifest_not_found")

    payload_manifest = manifest["payload"]
    proposed = payload_manifest.get("proposed_execution", {})
    if proposed.get("effect_class") != "read_only_internal":
        raise ValueError("only_read_only_internal_effect_class_supported")

    latest = _latest_packet_authorization(manifest["action_packet_id"])
    if not latest or latest["decision"] != "approve_for_execution_review":
        raise ValueError("current_packet_authorization_does_not_allow_execution_review")
    if latest["authorization_id"] != manifest["authorization_id"]:
        raise ValueError("manifest_source_authorization_is_stale")

    authorized = request.decision == "authorize_read_only_execution"
    if authorized:
        if not request.rationale.strip():
            raise ValueError("execution_authorization_rationale_required")
        if not request.scope_confirmed:
            raise ValueError("scope_confirmation_required")
        if not request.effects_confirmed:
            raise ValueError("effects_confirmation_required")
        if not request.capability_health_confirmed:
            raise ValueError("capability_health_confirmation_required")

    execution_authorization_id = str(uuid4())
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    expires_at = (now + timedelta(minutes=request.ttl_minutes)).isoformat() if authorized else None
    state = {
        "authorize_read_only_execution": "read_only_execution_authorized_not_dispatched",
        "request_changes": "execution_changes_requested",
        "hold": "execution_held",
        "reject": "execution_rejected",
    }[request.decision]

    payload = {
        "schema": SCHEMA,
        "execution_authorization_id": execution_authorization_id,
        "manifest_id": manifest_id,
        "manifest_receipt_sha256": manifest.get("manifest_receipt_sha256"),
        "action_packet_id": manifest["action_packet_id"],
        "created_at": created_at,
        "expires_at": expires_at,
        "decision": request.decision,
        "reviewer_label": request.reviewer_label.strip() or "operator",
        "rationale": request.rationale,
        "confirmations": {
            "scope_confirmed": bool(request.scope_confirmed),
            "effects_confirmed": bool(request.effects_confirmed),
            "capability_health_confirmed": bool(request.capability_health_confirmed),
        },
        "authorized_contract": {
            "capability_id": proposed.get("capability_id"),
            "contract_id": proposed.get("contract_id"),
            "effect_class": proposed.get("effect_class"),
            "action_kind": proposed.get("action_kind"),
            "operations": proposed.get("operations", []),
        },
        "state": state,
        "authority": {
            "human_execution_authorization_recorded": authorized,
            "execution_authorized": authorized,
            "authorized_effect_class": "read_only_internal" if authorized else "none",
            "dispatch_permitted": False,
            "external_write_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "credential_change_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": (
            "Create a separate dispatch request that revalidates expiry, latest authorization, contract, and live capability health. This record does not dispatch."
            if authorized
            else "No dispatch may be prepared from this disposition."
        ),
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT execution_authorization_receipt_sha256 FROM execution_authorizations ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["execution_authorization_receipt_sha256"] if previous else ""
        material = {
            "schema": SCHEMA,
            "execution_authorization_id": execution_authorization_id,
            "manifest_id": manifest_id,
            "action_packet_id": manifest["action_packet_id"],
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_execution_authorization_receipt_sha256": previous_receipt,
        }
        receipt = _sha256(material)
        conn.execute(
            """
            INSERT INTO execution_authorizations (
                execution_authorization_id, manifest_id, action_packet_id,
                created_at, expires_at, decision, reviewer_label, state,
                payload_json, payload_sha256,
                previous_execution_authorization_receipt_sha256,
                execution_authorization_receipt_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_authorization_id,
                manifest_id,
                manifest["action_packet_id"],
                created_at,
                expires_at,
                request.decision,
                payload["reviewer_label"],
                state,
                _canonical(payload),
                payload_sha,
                previous_receipt,
                receipt,
            ),
        )

    return {
        "schema": SCHEMA,
        "execution_authorization_id": execution_authorization_id,
        "manifest_id": manifest_id,
        "action_packet_id": manifest["action_packet_id"],
        "created_at": created_at,
        "expires_at": expires_at,
        "decision": request.decision,
        "state": state,
        "payload_sha256": payload_sha,
        "previous_execution_authorization_receipt_sha256": previous_receipt or None,
        "execution_authorization_receipt_sha256": receipt,
        "execution_authorized": authorized,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def get_execution_authorization(
    execution_authorization_id: str, include_payload: bool = True
) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM execution_authorizations WHERE execution_authorization_id = ? LIMIT 1",
            (execution_authorization_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def list_execution_authorizations(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, execution_authorization_id, manifest_id,
                   action_packet_id, created_at, expires_at, decision,
                   reviewer_label, state, payload_sha256,
                   previous_execution_authorization_receipt_sha256,
                   execution_authorization_receipt_sha256
            FROM execution_authorizations
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_execution_authorization_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM execution_authorizations ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_execution_authorization_id": row["execution_authorization_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_execution_authorization_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_execution_authorization_id": row["execution_authorization_id"], "reason": "previous_receipt_mismatch"}
        material = {
            "schema": SCHEMA,
            "execution_authorization_id": row["execution_authorization_id"],
            "manifest_id": row["manifest_id"],
            "action_packet_id": row["action_packet_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_execution_authorization_receipt_sha256": previous_receipt,
        }
        if _sha256(material) != row["execution_authorization_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_execution_authorization_id": row["execution_authorization_id"], "reason": "receipt_hash_mismatch"}
        previous_receipt = row["execution_authorization_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_execution_authorization_receipt_sha256": previous_receipt or None,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
