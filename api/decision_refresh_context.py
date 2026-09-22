from __future__ import annotations

import sqlite3
from typing import Any

from api.lineage_guard import assert_review_record_current
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_decision_refresh_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        returned = conn.execute(
            """
            SELECT evidence_return_id,execution_receipt_id,record_id,created_at,
                   state,evidence_return_receipt_sha256,sequence
            FROM evidence_return_packets
            WHERE record_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if not returned:
            return {
                "schema": "vmi.decision-refresh-context.v1",
                "record_id": record_id,
                "ready": False,
                "reason": "evidence_return_required",
                "external_actions_executed": 0,
            }
        item = dict(returned)
        existing = conn.execute(
            """
            SELECT refresh_id,evidence_return_id,record_id,prior_packet_id,
                   created_at,state,refresh_receipt_sha256,sequence
            FROM decision_refresh_packets
            WHERE evidence_return_id = ?
            LIMIT 1
            """,
            (item["evidence_return_id"],),
        ).fetchone()

    if item.get("state") != "returned_for_review":
        return {
            "schema": "vmi.decision-refresh-context.v1",
            "record_id": record_id,
            "evidence_return": item,
            "ready": False,
            "reason": "evidence_return_not_ready_for_refresh",
            "external_actions_executed": 0,
        }
    if existing:
        return {
            "schema": "vmi.decision-refresh-context.v1",
            "record_id": record_id,
            "evidence_return": item,
            "existing_refresh": dict(existing),
            "ready": False,
            "reason": "evidence_return_already_refreshed",
            "external_actions_executed": 0,
        }
    return {
        "schema": "vmi.decision-refresh-context.v1",
        "record_id": record_id,
        "ready": True,
        "reason": None,
        "evidence_return": item,
        "automatic_gap_resolution_permitted": False,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "successor_review_created": False,
        "next_gate": "Explicitly create a refreshed human-review snapshot. Prior gaps remain unresolved until a human reviews them.",
        "external_actions_executed": 0,
    }
