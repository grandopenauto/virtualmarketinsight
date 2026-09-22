from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from api.bounded_actions import get_bounded_action
from api.dispatch_tickets import get_dispatch_ticket
from api.execution_review import get_execution_review_manifest
from api.read_only_runner import get_execution_receipt
from api.review_events import get_review_event
from api.review_ledger import get_record, ledger_path

SCHEMA = "vmi.evidence-return.v1"


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
        CREATE TABLE IF NOT EXISTS evidence_return_packets (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_return_id TEXT NOT NULL UNIQUE,
            execution_receipt_id TEXT NOT NULL UNIQUE,
            dispatch_ticket_id TEXT NOT NULL,
            action_packet_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_evidence_return_receipt_sha256 TEXT,
            evidence_return_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_return_record ON evidence_return_packets(record_id, sequence)"
    )
    return conn


def _evidence_summary(result: Any) -> dict[str, Any]:
    if isinstance(result, list):
        return {"shape": "list", "item_count": len(result)}
    if isinstance(result, dict):
        summary: dict[str, Any] = {"shape": "object", "top_level_key_count": len(result)}
        for key in ("items", "opportunities", "results", "data"):
            value = result.get(key)
            if isinstance(value, list):
                summary["primary_collection"] = key
                summary["item_count"] = len(value)
                break
        return summary
    return {"shape": type(result).__name__}


def prepare_evidence_return(execution_receipt_id: str) -> dict[str, Any]:
    execution = get_execution_receipt(execution_receipt_id, include_result=True)
    if not execution:
        raise KeyError("execution_receipt_not_found")
    if execution.get("status") != "completed":
        raise ValueError("only_completed_execution_receipts_can_return_evidence")

    with _connect() as conn:
        existing = conn.execute(
            "SELECT evidence_return_id FROM evidence_return_packets WHERE execution_receipt_id = ? LIMIT 1",
            (execution_receipt_id,),
        ).fetchone()
    if existing:
        raise ValueError("execution_receipt_already_returned")

    ticket = get_dispatch_ticket(execution["dispatch_ticket_id"], include_payload=True)
    if not ticket:
        raise KeyError("dispatch_ticket_not_found")
    manifest = get_execution_review_manifest(ticket["manifest_id"], include_payload=True)
    if not manifest:
        raise KeyError("execution_review_manifest_not_found")
    action = get_bounded_action(manifest["action_packet_id"], include_payload=True)
    if not action:
        raise KeyError("bounded_action_packet_not_found")
    event = get_review_event(action["event_id"], include_payload=True)
    if not event:
        raise KeyError("review_event_not_found")
    review = get_record(event["record_id"], include_payload=True)
    if not review:
        raise KeyError("review_record_not_found")

    result = execution.get("result")
    evidence_return_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": SCHEMA,
        "evidence_return_id": evidence_return_id,
        "execution_receipt_id": execution_receipt_id,
        "execution_receipt_sha256": execution.get("execution_receipt_sha256"),
        "result_sha256": execution.get("result_sha256"),
        "dispatch_ticket_id": ticket["dispatch_ticket_id"],
        "dispatch_ticket_receipt_sha256": ticket.get("dispatch_ticket_receipt_sha256"),
        "manifest_id": manifest["manifest_id"],
        "action_packet_id": action["action_packet_id"],
        "event_id": event["event_id"],
        "record_id": review["record_id"],
        "created_at": created_at,
        "state": "returned_for_review",
        "source": {
            "capability_id": execution.get("capability_id"),
            "contract_id": execution.get("contract_id"),
            "operation": execution.get("operation"),
            "http_status": execution.get("http_status"),
        },
        "evidence_summary": _evidence_summary(result),
        "evidence": result,
        "authority": {
            "evidence_ingested": True,
            "approval_recorded": False,
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_write_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": "Use this returned evidence in a new human-reviewed decision refresh. No approval, authorization, dispatch, or execution is created by the return packet.",
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT evidence_return_receipt_sha256 FROM evidence_return_packets ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["evidence_return_receipt_sha256"] if previous else ""
        material = {
            "schema": SCHEMA,
            "evidence_return_id": evidence_return_id,
            "execution_receipt_id": execution_receipt_id,
            "record_id": review["record_id"],
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_evidence_return_receipt_sha256": previous_receipt,
        }
        receipt = _sha256(material)
        try:
            conn.execute(
                """
                INSERT INTO evidence_return_packets (
                    evidence_return_id, execution_receipt_id, dispatch_ticket_id,
                    action_packet_id, record_id, created_at, state, payload_json,
                    payload_sha256, previous_evidence_return_receipt_sha256,
                    evidence_return_receipt_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_return_id,
                    execution_receipt_id,
                    ticket["dispatch_ticket_id"],
                    action["action_packet_id"],
                    review["record_id"],
                    created_at,
                    "returned_for_review",
                    _canonical(payload),
                    payload_sha,
                    previous_receipt,
                    receipt,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("execution_receipt_already_returned") from exc

    return {
        "schema": SCHEMA,
        "evidence_return_id": evidence_return_id,
        "execution_receipt_id": execution_receipt_id,
        "dispatch_ticket_id": ticket["dispatch_ticket_id"],
        "action_packet_id": action["action_packet_id"],
        "record_id": review["record_id"],
        "created_at": created_at,
        "state": "returned_for_review",
        "payload_sha256": payload_sha,
        "previous_evidence_return_receipt_sha256": previous_receipt or None,
        "evidence_return_receipt_sha256": receipt,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def get_evidence_return(evidence_return_id: str, include_payload: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM evidence_return_packets WHERE evidence_return_id = ? LIMIT 1",
            (evidence_return_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def list_evidence_returns(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, evidence_return_id, execution_receipt_id,
                   dispatch_ticket_id, action_packet_id, record_id, created_at,
                   state, payload_sha256, previous_evidence_return_receipt_sha256,
                   evidence_return_receipt_sha256
            FROM evidence_return_packets
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_evidence_return_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM evidence_return_packets ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_evidence_return_id": row["evidence_return_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_evidence_return_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_evidence_return_id": row["evidence_return_id"], "reason": "previous_receipt_mismatch"}
        material = {
            "schema": SCHEMA,
            "evidence_return_id": row["evidence_return_id"],
            "execution_receipt_id": row["execution_receipt_id"],
            "record_id": row["record_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_evidence_return_receipt_sha256": previous_receipt,
        }
        if _sha256(material) != row["evidence_return_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_evidence_return_id": row["evidence_return_id"], "reason": "receipt_hash_mismatch"}
        previous_receipt = row["evidence_return_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_evidence_return_receipt_sha256": previous_receipt or None,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
