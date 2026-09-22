from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from api.review_ledger import get_record, ledger_path

SCHEMA = "vmi.review-event.v1"
ReviewDecision = Literal[
    "request_more_evidence",
    "resolve_capability_gap",
    "prepare_bounded_action",
    "stop",
]


class ReviewEventInput(BaseModel):
    decision: ReviewDecision
    reviewer_label: str = Field(default="operator", max_length=120)
    note: str = Field(default="", max_length=1600)
    scope: str = Field(default="", max_length=800)


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
        CREATE TABLE IF NOT EXISTS review_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            record_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer_label TEXT NOT NULL,
            note TEXT NOT NULL,
            scope TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_event_receipt_sha256 TEXT,
            event_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_events_record_id ON review_events(record_id, sequence)"
    )
    return conn


def append_review_event(record_id: str, event: ReviewEventInput) -> dict[str, Any]:
    record = get_record(record_id, include_payload=False)
    if not record:
        raise KeyError("review_record_not_found")

    event_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": SCHEMA,
        "event_id": event_id,
        "record_id": record_id,
        "record_receipt_sha256": record.get("receipt_sha256"),
        "decision": event.decision,
        "reviewer_label": event.reviewer_label.strip() or "operator",
        "note": event.note,
        "scope": event.scope,
        "state": "review_recorded_no_authority",
        "approval_recorded": False,
        "execution_permitted": False,
        "external_actions_executed": 0,
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT event_receipt_sha256 FROM review_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["event_receipt_sha256"] if previous else ""
        receipt_material = {
            "schema": SCHEMA,
            "event_id": event_id,
            "record_id": record_id,
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_event_receipt_sha256": previous_receipt,
        }
        event_receipt = _sha256(receipt_material)
        conn.execute(
            """
            INSERT INTO review_events (
                event_id, record_id, created_at, decision, reviewer_label,
                note, scope, state, payload_json, payload_sha256,
                previous_event_receipt_sha256, event_receipt_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                record_id,
                created_at,
                event.decision,
                payload["reviewer_label"],
                event.note,
                event.scope,
                "review_recorded_no_authority",
                _canonical(payload),
                payload_sha,
                previous_receipt,
                event_receipt,
            ),
        )

    return {
        "schema": SCHEMA,
        "event_id": event_id,
        "record_id": record_id,
        "created_at": created_at,
        "decision": event.decision,
        "reviewer_label": payload["reviewer_label"],
        "state": "review_recorded_no_authority",
        "payload_sha256": payload_sha,
        "previous_event_receipt_sha256": previous_receipt or None,
        "event_receipt_sha256": event_receipt,
        "approval_recorded": False,
        "execution_permitted": False,
        "external_actions_executed": 0,
        "next_gate": _next_gate(event.decision),
    }


def _next_gate(decision: str) -> str:
    return {
        "request_more_evidence": "Prepare another bounded evidence pass; do not execute external actions.",
        "resolve_capability_gap": "Resolve or document the capability gap before preparing consequential action.",
        "prepare_bounded_action": "Prepare a separate bounded action artifact for later human approval; this event does not approve it.",
        "stop": "Stop this review path. No further action is authorized by this event.",
    }[decision]


def get_review_event(event_id: str, include_payload: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM review_events WHERE event_id = ? LIMIT 1", (event_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def list_review_events(record_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not get_record(record_id, include_payload=False):
        raise KeyError("review_record_not_found")
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, event_id, record_id, created_at, decision,
                   reviewer_label, note, scope, state, payload_sha256,
                   previous_event_receipt_sha256, event_receipt_sha256
            FROM review_events
            WHERE record_id = ?
            ORDER BY sequence ASC
            LIMIT ?
            """,
            (record_id, safe_limit),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_event_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM review_events ORDER BY sequence ASC").fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_event_id": row["event_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_event_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_event_id": row["event_id"], "reason": "previous_event_receipt_mismatch"}
        receipt_material = {
            "schema": SCHEMA,
            "event_id": row["event_id"],
            "record_id": row["record_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_event_receipt_sha256": previous_receipt,
        }
        if _sha256(receipt_material) != row["event_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_event_id": row["event_id"], "reason": "event_receipt_hash_mismatch"}
        previous_receipt = row["event_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_event_receipt_sha256": previous_receipt or None,
        "approval_authority": False,
        "execution_authority": False,
        "external_actions_executed": 0,
    }
