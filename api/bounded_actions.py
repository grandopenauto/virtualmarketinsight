from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from api.review_events import get_review_event
from api.review_ledger import get_record, ledger_path

SCHEMA = "vmi.bounded-action-packet.v1"
ActionKind = Literal[
    "research_only",
    "evidence_refresh",
    "capability_gap_resolution",
    "internal_analysis_preparation",
]


class BoundedActionInput(BaseModel):
    action_kind: ActionKind
    objective: str = Field(min_length=3, max_length=1200)
    scope: str = Field(default="", max_length=1200)
    target_capability: str = Field(default="", max_length=160)


_ALLOWED_BY_DECISION: dict[str, set[str]] = {
    "request_more_evidence": {"evidence_refresh"},
    "resolve_capability_gap": {"capability_gap_resolution"},
    "prepare_bounded_action": {"research_only", "internal_analysis_preparation"},
    "stop": set(),
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
        CREATE TABLE IF NOT EXISTS bounded_action_packets (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            action_packet_id TEXT NOT NULL UNIQUE,
            record_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            action_kind TEXT NOT NULL,
            objective TEXT NOT NULL,
            scope TEXT NOT NULL,
            target_capability TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_packet_receipt_sha256 TEXT,
            packet_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bounded_actions_record_id ON bounded_action_packets(record_id, sequence)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bounded_actions_event_id ON bounded_action_packets(event_id, sequence)"
    )
    return conn


def prepare_bounded_action(event_id: str, request: BoundedActionInput) -> dict[str, Any]:
    event = get_review_event(event_id, include_payload=True)
    if not event:
        raise KeyError("review_event_not_found")

    decision = event["decision"]
    allowed = _ALLOWED_BY_DECISION.get(decision, set())
    if request.action_kind not in allowed:
        raise ValueError("action_kind_not_allowed_for_review_decision")

    record = get_record(event["record_id"], include_payload=True)
    if not record:
        raise KeyError("review_record_not_found")

    action_packet_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": SCHEMA,
        "action_packet_id": action_packet_id,
        "record_id": event["record_id"],
        "event_id": event_id,
        "created_at": created_at,
        "action_kind": request.action_kind,
        "objective": request.objective,
        "scope": request.scope,
        "target_capability": request.target_capability,
        "state": "prepared_not_approved",
        "source_receipts": {
            "review_record": record.get("receipt_sha256"),
            "review_event": event.get("event_receipt_sha256"),
        },
        "allowed_effects": [
            "prepare internal planning artifacts",
            "perform bounded read-only evidence work only after a separate approved mechanism exists",
        ],
        "prohibited_effects": [
            "external outreach",
            "capital movement",
            "trading or securities transactions",
            "purchases or payment initiation",
            "credential or permission changes",
            "system execution or dispatch",
            "self-approval",
        ],
        "preconditions": [
            {"id": "human_scope_review", "required": True, "satisfied": False},
            {"id": "capability_contract_review", "required": True, "satisfied": False},
            {"id": "explicit_execution_approval", "required": True, "satisfied": False},
        ],
        "authority": {
            "approval_recorded": False,
            "self_approval_permitted": False,
            "execution_permitted": False,
            "analysis_generation_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": "Human review of this bounded action packet. Preparation does not authorize dispatch or execution.",
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT packet_receipt_sha256 FROM bounded_action_packets ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["packet_receipt_sha256"] if previous else ""
        receipt_material = {
            "schema": SCHEMA,
            "action_packet_id": action_packet_id,
            "record_id": event["record_id"],
            "event_id": event_id,
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_packet_receipt_sha256": previous_receipt,
        }
        packet_receipt = _sha256(receipt_material)
        conn.execute(
            """
            INSERT INTO bounded_action_packets (
                action_packet_id, record_id, event_id, created_at, action_kind,
                objective, scope, target_capability, state, payload_json,
                payload_sha256, previous_packet_receipt_sha256, packet_receipt_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_packet_id,
                event["record_id"],
                event_id,
                created_at,
                request.action_kind,
                request.objective,
                request.scope,
                request.target_capability,
                "prepared_not_approved",
                _canonical(payload),
                payload_sha,
                previous_receipt,
                packet_receipt,
            ),
        )

    return {
        "schema": SCHEMA,
        "action_packet_id": action_packet_id,
        "record_id": event["record_id"],
        "event_id": event_id,
        "created_at": created_at,
        "action_kind": request.action_kind,
        "state": "prepared_not_approved",
        "payload_sha256": payload_sha,
        "previous_packet_receipt_sha256": previous_receipt or None,
        "packet_receipt_sha256": packet_receipt,
        "approval_recorded": False,
        "execution_permitted": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def get_bounded_action(action_packet_id: str, include_payload: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM bounded_action_packets WHERE action_packet_id = ? LIMIT 1",
            (action_packet_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def list_bounded_actions(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, action_packet_id, record_id, event_id, created_at,
                   action_kind, objective, scope, target_capability, state,
                   payload_sha256, previous_packet_receipt_sha256, packet_receipt_sha256
            FROM bounded_action_packets
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_bounded_action_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bounded_action_packets ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_action_packet_id": row["action_packet_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_packet_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_action_packet_id": row["action_packet_id"], "reason": "previous_packet_receipt_mismatch"}
        receipt_material = {
            "schema": SCHEMA,
            "action_packet_id": row["action_packet_id"],
            "record_id": row["record_id"],
            "event_id": row["event_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_packet_receipt_sha256": previous_receipt,
        }
        if _sha256(receipt_material) != row["packet_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_action_packet_id": row["action_packet_id"], "reason": "packet_receipt_hash_mismatch"}
        previous_receipt = row["packet_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_packet_receipt_sha256": previous_receipt or None,
        "approval_authority": False,
        "execution_authority": False,
        "external_actions_executed": 0,
    }
