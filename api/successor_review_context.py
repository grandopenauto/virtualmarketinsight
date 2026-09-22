from __future__ import annotations

import sqlite3
from typing import Any

from api.lineage_guard import assert_review_record_current
from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_successor_review_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        refresh = conn.execute(
            """
            SELECT refresh_id,evidence_return_id,record_id,prior_packet_id,
                   created_at,state,refresh_receipt_sha256,sequence
            FROM decision_refresh_packets
            WHERE record_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if not refresh:
            return {
                "schema": "vmi.successor-review-context.v1",
                "record_id": record_id,
                "ready": False,
                "reason": "decision_refresh_required",
                "external_actions_executed": 0,
            }
        item = dict(refresh)
        existing = conn.execute(
            """
            SELECT successor_id,refresh_id,parent_record_id,record_id,generation,
                   created_at,state,successor_receipt_sha256,sequence
            FROM successor_review_records
            WHERE refresh_id = ?
            LIMIT 1
            """,
            (item["refresh_id"],),
        ).fetchone()

    if item.get("state") != "refreshed_for_human_review":
        return {
            "schema": "vmi.successor-review-context.v1",
            "record_id": record_id,
            "refresh": item,
            "ready": False,
            "reason": "decision_refresh_not_ready_for_successor",
            "external_actions_executed": 0,
        }
    if existing:
        return {
            "schema": "vmi.successor-review-context.v1",
            "record_id": record_id,
            "refresh": item,
            "existing_successor": dict(existing),
            "ready": False,
            "reason": "decision_refresh_already_has_successor_review",
            "external_actions_executed": 0,
        }
    return {
        "schema": "vmi.successor-review-context.v1",
        "record_id": record_id,
        "ready": True,
        "reason": None,
        "refresh": item,
        "authority_inherited": False,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "next_gate": "Explicitly create a new prepared_not_approved review generation. No prior authorization or execution authority carries forward.",
        "external_actions_executed": 0,
    }
