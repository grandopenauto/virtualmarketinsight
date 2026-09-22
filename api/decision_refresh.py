from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from api.evidence_return import get_evidence_return
from api.review_ledger import get_record, ledger_path

SCHEMA = "vmi.decision-refresh.v1"


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
        CREATE TABLE IF NOT EXISTS decision_refresh_packets (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_id TEXT NOT NULL UNIQUE,
            evidence_return_id TEXT NOT NULL UNIQUE,
            record_id TEXT NOT NULL,
            prior_packet_id TEXT,
            created_at TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_refresh_receipt_sha256 TEXT,
            refresh_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_refresh_record ON decision_refresh_packets(record_id, sequence)"
    )
    return conn


def prepare_decision_refresh(evidence_return_id: str) -> dict[str, Any]:
    evidence_return = get_evidence_return(evidence_return_id, include_payload=True)
    if not evidence_return:
        raise KeyError("evidence_return_not_found")
    if evidence_return.get("state") != "returned_for_review":
        raise ValueError("evidence_return_not_ready_for_refresh")

    with _connect() as conn:
        existing = conn.execute(
            "SELECT refresh_id FROM decision_refresh_packets WHERE evidence_return_id = ? LIMIT 1",
            (evidence_return_id,),
        ).fetchone()
    if existing:
        raise ValueError("evidence_return_already_refreshed")

    record = get_record(evidence_return["record_id"], include_payload=True)
    if not record:
        raise KeyError("review_record_not_found")

    record_payload = record.get("payload", {})
    prior_packet = record_payload.get("decision_packet", {}) or {}
    returned = evidence_return.get("payload", {})
    returned_summary = returned.get("evidence_summary", {}) or {}
    prior_summary = prior_packet.get("evidence_summary", {}) or {}

    prior_success = int(prior_summary.get("successful_reads", 0) or 0)
    prior_attempts = int(prior_summary.get("attempted_reads", 0) or 0)
    refreshed_success = prior_success + 1
    refreshed_attempts = prior_attempts + 1
    if refreshed_attempts and refreshed_success == refreshed_attempts:
        refreshed_state = "all_recorded_reads_succeeded"
    elif refreshed_success > 0:
        refreshed_state = "partial_with_returned_evidence"
    else:
        refreshed_state = "returned_evidence_only"

    refresh_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": SCHEMA,
        "refresh_id": refresh_id,
        "evidence_return_id": evidence_return_id,
        "evidence_return_receipt_sha256": evidence_return.get("evidence_return_receipt_sha256"),
        "record_id": record["record_id"],
        "record_receipt_sha256": record.get("receipt_sha256"),
        "prior_packet_id": prior_packet.get("packet_id"),
        "created_at": created_at,
        "state": "refreshed_for_human_review",
        "intent": prior_packet.get("intent", {}),
        "execution_graph": prior_packet.get("execution_graph", {}),
        "capability_plan": prior_packet.get("capability_plan", []),
        "prior_evidence_summary": prior_summary,
        "returned_evidence": {
            "source": returned.get("source", {}),
            "summary": returned_summary,
            "result_sha256": returned.get("result_sha256"),
            "evidence": returned.get("evidence"),
        },
        "refreshed_evidence_summary": {
            "state": refreshed_state,
            "successful_reads": refreshed_success,
            "attempted_reads": refreshed_attempts,
            "new_returned_read_count": 1,
        },
        "gap_review": {
            "prior_gaps": prior_packet.get("gaps", []),
            "automatic_gap_resolution_permitted": False,
            "instruction": "Returned evidence may inform gap review, but no prior gap is automatically marked resolved.",
        },
        "prepared_next_action": prior_packet.get("prepared_next_action"),
        "review_options": prior_packet.get(
            "review_options",
            ["request_more_evidence", "resolve_capability_gap", "prepare_bounded_action", "stop"],
        ),
        "authority": {
            "mode": "refreshed_evidence_for_review_only",
            "human_review_required": True,
            "approval_recorded": False,
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_write_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": "Human review of the refreshed evidence context. No approval, bounded action, authorization, dispatch, or execution is created automatically.",
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT refresh_receipt_sha256 FROM decision_refresh_packets ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["refresh_receipt_sha256"] if previous else ""
        material = {
            "schema": SCHEMA,
            "refresh_id": refresh_id,
            "evidence_return_id": evidence_return_id,
            "record_id": record["record_id"],
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_refresh_receipt_sha256": previous_receipt,
        }
        receipt = _sha256(material)
        try:
            conn.execute(
                """
                INSERT INTO decision_refresh_packets (
                    refresh_id, evidence_return_id, record_id, prior_packet_id,
                    created_at, state, payload_json, payload_sha256,
                    previous_refresh_receipt_sha256, refresh_receipt_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    refresh_id,
                    evidence_return_id,
                    record["record_id"],
                    prior_packet.get("packet_id"),
                    created_at,
                    "refreshed_for_human_review",
                    _canonical(payload),
                    payload_sha,
                    previous_receipt,
                    receipt,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("evidence_return_already_refreshed") from exc

    return {
        "schema": SCHEMA,
        "refresh_id": refresh_id,
        "evidence_return_id": evidence_return_id,
        "record_id": record["record_id"],
        "prior_packet_id": prior_packet.get("packet_id"),
        "created_at": created_at,
        "state": "refreshed_for_human_review",
        "payload_sha256": payload_sha,
        "previous_refresh_receipt_sha256": previous_receipt or None,
        "refresh_receipt_sha256": receipt,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def get_decision_refresh(refresh_id: str, include_payload: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM decision_refresh_packets WHERE refresh_id = ? LIMIT 1",
            (refresh_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def list_decision_refreshes(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, refresh_id, evidence_return_id, record_id,
                   prior_packet_id, created_at, state, payload_sha256,
                   previous_refresh_receipt_sha256, refresh_receipt_sha256
            FROM decision_refresh_packets
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_decision_refresh_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM decision_refresh_packets ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_refresh_id": row["refresh_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_refresh_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_refresh_id": row["refresh_id"], "reason": "previous_receipt_mismatch"}
        material = {
            "schema": SCHEMA,
            "refresh_id": row["refresh_id"],
            "evidence_return_id": row["evidence_return_id"],
            "record_id": row["record_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_refresh_receipt_sha256": previous_receipt,
        }
        if _sha256(material) != row["refresh_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_refresh_id": row["refresh_id"], "reason": "receipt_hash_mismatch"}
        previous_receipt = row["refresh_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_refresh_receipt_sha256": previous_receipt or None,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
