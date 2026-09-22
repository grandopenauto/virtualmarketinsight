from __future__ import annotations

import json
import sqlite3
from typing import Any

from api.review_ledger import ledger_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _record_has_successor(conn: sqlite3.Connection, record_id: str) -> bool:
    rows = conn.execute(
        "SELECT payload_json FROM review_records WHERE record_type = 'successor_review_record'"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        cycle = payload.get("review_cycle", {}) or {}
        if cycle.get("parent_record_id") == record_id:
            return True
    return False


def assert_review_event_current(event_id: str) -> dict[str, Any]:
    with _connect() as conn:
        event = conn.execute(
            "SELECT event_id, record_id, decision, sequence FROM review_events WHERE event_id = ? LIMIT 1",
            (event_id,),
        ).fetchone()
        if not event:
            raise KeyError("review_event_not_found")
        latest = conn.execute(
            "SELECT event_id, record_id, decision, sequence FROM review_events WHERE record_id = ? ORDER BY sequence DESC LIMIT 1",
            (event["record_id"],),
        ).fetchone()
        if not latest or latest["event_id"] != event_id:
            raise ValueError("review_event_is_not_latest_for_record")
        if _record_has_successor(conn, event["record_id"]):
            raise ValueError("review_record_superseded_by_successor_cycle")
        return dict(event)


def assert_action_packet_current(action_packet_id: str) -> dict[str, Any]:
    with _connect() as conn:
        packet = conn.execute(
            "SELECT action_packet_id, record_id, event_id, action_kind, sequence FROM bounded_action_packets WHERE action_packet_id = ? LIMIT 1",
            (action_packet_id,),
        ).fetchone()
        if not packet:
            raise KeyError("bounded_action_packet_not_found")
    assert_review_event_current(packet["event_id"])
    return dict(packet)


def inspect_action_packet_freshness(action_packet_id: str) -> dict[str, Any]:
    try:
        packet = assert_action_packet_current(action_packet_id)
        return {
            "current": True,
            "action_packet_id": action_packet_id,
            "record_id": packet["record_id"],
            "event_id": packet["event_id"],
            "reason": None,
        }
    except (KeyError, ValueError) as exc:
        return {
            "current": False,
            "action_packet_id": action_packet_id,
            "reason": str(exc),
        }
