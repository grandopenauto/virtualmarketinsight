from __future__ import annotations

import sqlite3
from typing import Any

from api.lineage_guard import assert_review_record_current
from api.read_only_runner import get_execution_receipt
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_evidence_return_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        execution = conn.execute(
            """
            SELECT e.execution_receipt_id,e.dispatch_ticket_id,e.created_at,
                   e.capability_id,e.contract_id,e.operation,e.status,e.http_status,
                   e.result_sha256,e.execution_receipt_sha256,e.sequence
            FROM read_only_execution_receipts e
            JOIN dispatch_tickets t ON t.dispatch_ticket_id = e.dispatch_ticket_id
            JOIN bounded_action_packets a ON a.action_packet_id = t.action_packet_id
            WHERE a.record_id = ?
            ORDER BY e.sequence DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if not execution:
            return {
                "schema": "vmi.evidence-return-context.v1",
                "record_id": record_id,
                "ready": False,
                "reason": "completed_execution_receipt_required",
                "external_actions_executed": 0,
            }
        item = dict(execution)
        existing = conn.execute(
            """
            SELECT evidence_return_id,execution_receipt_id,created_at,state,
                   evidence_return_receipt_sha256,sequence
            FROM evidence_return_packets
            WHERE execution_receipt_id = ?
            LIMIT 1
            """,
            (item["execution_receipt_id"],),
        ).fetchone()

    if item.get("status") != "completed":
        return {
            "schema": "vmi.evidence-return-context.v1",
            "record_id": record_id,
            "execution": item,
            "ready": False,
            "reason": "latest_execution_not_completed",
            "external_actions_executed": 0,
        }
    if existing:
        return {
            "schema": "vmi.evidence-return-context.v1",
            "record_id": record_id,
            "execution": item,
            "existing_evidence_return": dict(existing),
            "ready": False,
            "reason": "execution_receipt_already_returned",
            "external_actions_executed": 0,
        }

    full = get_execution_receipt(str(item["execution_receipt_id"]), include_result=False)
    return {
        "schema": "vmi.evidence-return-context.v1",
        "record_id": record_id,
        "ready": True,
        "reason": None,
        "execution": item,
        "receipt_integrity": {
            "result_sha256": (full or {}).get("result_sha256") or item.get("result_sha256"),
            "execution_receipt_sha256": (full or {}).get("execution_receipt_sha256") or item.get("execution_receipt_sha256"),
        },
        "raw_result_exposed": False,
        "next_gate": "Explicitly return this completed execution result into the review lineage as evidence. No decision refresh is created automatically.",
        "evidence_return_created": False,
        "decision_refresh_created": False,
        "successor_review_created": False,
        "external_actions_executed": 0,
    }
