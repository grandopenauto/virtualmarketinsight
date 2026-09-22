from __future__ import annotations

import sqlite3
from typing import Any

from api.lineage_guard import assert_review_record_current, assert_review_event_current
from api.review_ledger import ledger_path

ALLOWED_BY_DECISION: dict[str, list[str]] = {
    "request_more_evidence": ["evidence_refresh"],
    "resolve_capability_gap": ["capability_gap_resolution"],
    "prepare_bounded_action": ["research_only", "internal_analysis_preparation"],
    "stop": [],
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def build_action_context(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    with _connect() as conn:
        event = conn.execute(
            "SELECT event_id, record_id, created_at, decision, state, sequence FROM review_events WHERE record_id = ? ORDER BY sequence DESC LIMIT 1",
            (record_id,),
        ).fetchone()
        if not event:
            return {
                "schema": "vmi.operator-action-context.v1",
                "record_id": record_id,
                "current_review_event": None,
                "allowed_action_kinds": [],
                "can_prepare_bounded_action": False,
                "reason": "human_review_event_required",
                "existing_latest_action": None,
                "approval_authority": False,
                "execution_authority": False,
                "dispatch_authority": False,
                "external_actions_executed": 0,
            }

        event_item = dict(event)
        assert_review_event_current(str(event_item["event_id"]))
        allowed = list(ALLOWED_BY_DECISION.get(str(event_item.get("decision")), []))
        latest_action = conn.execute(
            "SELECT action_packet_id,event_id,created_at,action_kind,target_capability,state,sequence FROM bounded_action_packets WHERE event_id = ? ORDER BY sequence DESC LIMIT 1",
            (event_item["event_id"],),
        ).fetchone()

    return {
        "schema": "vmi.operator-action-context.v1",
        "record_id": record_id,
        "current_review_event": {
            "event_id": event_item["event_id"],
            "created_at": event_item.get("created_at"),
            "decision": event_item.get("decision"),
            "state": event_item.get("state"),
        },
        "allowed_action_kinds": allowed,
        "can_prepare_bounded_action": bool(allowed),
        "reason": None if allowed else "review_decision_does_not_allow_bounded_action",
        "existing_latest_action": dict(latest_action) if latest_action else None,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
