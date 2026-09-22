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


def assert_review_record_current(record_id: str) -> dict[str, Any]:
    with _connect() as conn:
        record = conn.execute(
            "SELECT record_id, record_type, state, sequence FROM review_records WHERE record_id = ? LIMIT 1",
            (record_id,),
        ).fetchone()
        if not record:
            raise KeyError("review_record_not_found")
        if _record_has_successor(conn, record_id):
            raise ValueError("review_record_superseded_by_successor_cycle")
        return dict(record)


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
        latest = conn.execute(
            "SELECT action_packet_id, event_id, sequence FROM bounded_action_packets WHERE event_id = ? ORDER BY sequence DESC LIMIT 1",
            (packet["event_id"],),
        ).fetchone()
        if not latest or latest["action_packet_id"] != action_packet_id:
            raise ValueError("bounded_action_packet_is_not_latest_for_review_event")
    assert_review_event_current(packet["event_id"])
    return dict(packet)


def assert_execution_review_manifest_current(manifest_id: str) -> dict[str, Any]:
    with _connect() as conn:
        manifest = conn.execute(
            "SELECT manifest_id, authorization_id, action_packet_id, state, sequence FROM execution_review_manifests WHERE manifest_id = ? LIMIT 1",
            (manifest_id,),
        ).fetchone()
        if not manifest:
            raise KeyError("execution_review_manifest_not_found")
        latest = conn.execute(
            "SELECT manifest_id, action_packet_id, sequence FROM execution_review_manifests WHERE action_packet_id = ? ORDER BY sequence DESC LIMIT 1",
            (manifest["action_packet_id"],),
        ).fetchone()
        if not latest or latest["manifest_id"] != manifest_id:
            raise ValueError("execution_review_manifest_is_not_latest_for_action_packet")
    assert_action_packet_current(str(manifest["action_packet_id"]))
    return dict(manifest)


def assert_dispatch_ticket_current(dispatch_ticket_id: str) -> dict[str, Any]:
    with _connect() as conn:
        ticket = conn.execute(
            """
            SELECT dispatch_ticket_id,execution_authorization_id,manifest_id,
                   action_packet_id,state,sequence
            FROM dispatch_tickets
            WHERE dispatch_ticket_id = ?
            LIMIT 1
            """,
            (dispatch_ticket_id,),
        ).fetchone()
        if not ticket:
            raise KeyError("dispatch_ticket_not_found")
        latest = conn.execute(
            """
            SELECT dispatch_ticket_id,execution_authorization_id,sequence
            FROM dispatch_tickets
            WHERE execution_authorization_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (ticket["execution_authorization_id"],),
        ).fetchone()
        if not latest or latest["dispatch_ticket_id"] != dispatch_ticket_id:
            raise ValueError("dispatch_ticket_is_not_latest_for_execution_authorization")
    assert_execution_review_manifest_current(str(ticket["manifest_id"]))
    return dict(ticket)


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


def inspect_execution_review_manifest_freshness(manifest_id: str) -> dict[str, Any]:
    try:
        manifest = assert_execution_review_manifest_current(manifest_id)
        return {
            "current": True,
            "manifest_id": manifest_id,
            "action_packet_id": manifest["action_packet_id"],
            "authorization_id": manifest["authorization_id"],
            "reason": None,
        }
    except (KeyError, ValueError) as exc:
        return {
            "current": False,
            "manifest_id": manifest_id,
            "reason": str(exc),
        }


def inspect_dispatch_ticket_freshness(dispatch_ticket_id: str) -> dict[str, Any]:
    try:
        ticket = assert_dispatch_ticket_current(dispatch_ticket_id)
        return {
            "current": True,
            "dispatch_ticket_id": dispatch_ticket_id,
            "execution_authorization_id": ticket["execution_authorization_id"],
            "manifest_id": ticket["manifest_id"],
            "reason": None,
        }
    except (KeyError, ValueError) as exc:
        return {
            "current": False,
            "dispatch_ticket_id": dispatch_ticket_id,
            "reason": str(exc),
        }
