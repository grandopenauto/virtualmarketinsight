from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from api.decision_refresh import get_decision_refresh
from api.review_ledger import get_record, ledger_path, verify_chain

SCHEMA = "vmi.successor-review-record.v1"
RECORD_TYPE = "successor_review_record"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _successor_record_id(refresh_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"vmi-successor-review:{refresh_id}"))


def prepare_successor_review(refresh_id: str) -> dict[str, Any]:
    refresh = get_decision_refresh(refresh_id, include_payload=True)
    if not refresh:
        raise KeyError("decision_refresh_not_found")
    if refresh.get("state") != "refreshed_for_human_review":
        raise ValueError("decision_refresh_not_ready_for_successor_review")

    parent = get_record(refresh["record_id"], include_payload=True)
    if not parent:
        raise KeyError("parent_review_record_not_found")

    refresh_payload = refresh.get("payload", {})
    parent_payload = parent.get("payload", {})
    prior_packet = parent_payload.get("decision_packet", {}) or {}
    parent_cycle = parent_payload.get("review_cycle", {}) or {}
    generation = int(parent_cycle.get("generation", 0) or 0) + 1

    created_at = datetime.now(timezone.utc).isoformat()
    packet_id = str(uuid4())
    record_id = _successor_record_id(refresh_id)

    decision_packet = {
        "schema": "vmi.decision-packet.v2",
        "packet_id": packet_id,
        "request_id": prior_packet.get("request_id") or parent_payload.get("request_id"),
        "created_at": created_at,
        "intent": refresh_payload.get("intent", prior_packet.get("intent", {})),
        "execution_graph": refresh_payload.get("execution_graph", prior_packet.get("execution_graph", {})),
        "capability_plan": refresh_payload.get("capability_plan", prior_packet.get("capability_plan", [])),
        "capability_health": prior_packet.get("capability_health", []),
        "evidence": {
            "prior": prior_packet.get("evidence", {}),
            "returned": refresh_payload.get("returned_evidence", {}),
        },
        "evidence_summary": refresh_payload.get("refreshed_evidence_summary", {}),
        "gaps": (refresh_payload.get("gap_review", {}) or {}).get("prior_gaps", prior_packet.get("gaps", [])),
        "prepared_next_action": refresh_payload.get("prepared_next_action", prior_packet.get("prepared_next_action")),
        "review_options": refresh_payload.get(
            "review_options",
            ["request_more_evidence", "resolve_capability_gap", "prepare_bounded_action", "stop"],
        ),
        "authority": {
            "mode": "successor_review_preparation_only",
            "human_review_required": True,
            "approval_recorded": False,
            "external_execution_permitted": False,
            "analysis_generation_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": "Human review of this successor decision packet. No prior approval or execution authority carries forward.",
    }

    payload = {
        "schema": SCHEMA,
        "state": "prepared_not_approved",
        "request_id": decision_packet.get("request_id"),
        "packet_id": packet_id,
        "approval_id": None,
        "review_cycle": {
            "generation": generation,
            "parent_record_id": parent["record_id"],
            "parent_record_receipt_sha256": parent.get("receipt_sha256"),
            "decision_refresh_id": refresh_id,
            "decision_refresh_receipt_sha256": refresh.get("refresh_receipt_sha256"),
            "evidence_return_id": refresh.get("evidence_return_id"),
            "authority_inherited": False,
        },
        "decision_packet": decision_packet,
        "approval_envelope": None,
        "authority": {
            "approval_recorded": False,
            "self_approval_permitted": False,
            "execution_permitted": False,
            "dispatch_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": "Human review event. This successor record is a new review cycle and carries no prior authority forward.",
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT record_id FROM review_records WHERE record_id = ? LIMIT 1",
            (record_id,),
        ).fetchone()
        if existing:
            raise ValueError("decision_refresh_already_has_successor_review")

        previous = conn.execute(
            "SELECT receipt_sha256 FROM review_records ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["receipt_sha256"] if previous else ""
        receipt_material = {
            "schema": "vmi.review-ledger.v1",
            "record_id": record_id,
            "created_at": created_at,
            "record_type": RECORD_TYPE,
            "payload_sha256": payload_sha,
            "previous_receipt_sha256": previous_receipt,
        }
        receipt_sha = _sha256(receipt_material)
        try:
            conn.execute(
                """
                INSERT INTO review_records (
                    record_id, created_at, record_type, request_id, packet_id,
                    approval_id, state, payload_json, payload_sha256,
                    previous_receipt_sha256, receipt_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    created_at,
                    RECORD_TYPE,
                    payload.get("request_id"),
                    packet_id,
                    None,
                    "prepared_not_approved",
                    _canonical(payload),
                    payload_sha,
                    previous_receipt,
                    receipt_sha,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("decision_refresh_already_has_successor_review") from exc

    return {
        "schema": SCHEMA,
        "record_id": record_id,
        "record_type": RECORD_TYPE,
        "parent_record_id": parent["record_id"],
        "refresh_id": refresh_id,
        "packet_id": packet_id,
        "generation": generation,
        "created_at": created_at,
        "state": "prepared_not_approved",
        "payload_sha256": payload_sha,
        "previous_receipt_sha256": previous_receipt or None,
        "receipt_sha256": receipt_sha,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "authority_inherited": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def list_successor_reviews(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, record_id, created_at, record_type, request_id,
                   packet_id, state, payload_sha256, previous_receipt_sha256,
                   receipt_sha256, payload_json
            FROM review_records
            WHERE record_type = ?
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (RECORD_TYPE, safe_limit),
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        cycle = payload.get("review_cycle", {})
        item["generation"] = cycle.get("generation")
        item["parent_record_id"] = cycle.get("parent_record_id")
        item["refresh_id"] = cycle.get("decision_refresh_id")
        items.append(item)
    return items


def verify_successor_reviews() -> dict[str, Any]:
    ledger = verify_chain()
    if not ledger.get("ok"):
        return {
            "ok": False,
            "reason": "review_ledger_chain_failed",
            "ledger": ledger,
            "checked": 0,
        }

    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM review_records WHERE record_type = ? ORDER BY sequence ASC",
            (RECORD_TYPE,),
        ).fetchall()

    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        cycle = payload.get("review_cycle", {})
        parent_id = cycle.get("parent_record_id")
        refresh_id = cycle.get("decision_refresh_id")
        if not parent_id or not get_record(parent_id, include_payload=False):
            return {"ok": False, "checked": checked, "failed_record_id": row["record_id"], "reason": "parent_record_missing"}
        refresh = get_decision_refresh(refresh_id, include_payload=False) if refresh_id else None
        if not refresh:
            return {"ok": False, "checked": checked, "failed_record_id": row["record_id"], "reason": "decision_refresh_missing"}
        if refresh.get("record_id") != parent_id:
            return {"ok": False, "checked": checked, "failed_record_id": row["record_id"], "reason": "refresh_parent_mismatch"}
        if cycle.get("authority_inherited") is not False:
            return {"ok": False, "checked": checked, "failed_record_id": row["record_id"], "reason": "authority_inheritance_violation"}
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "review_ledger_chain_ok": True,
        "authority_inheritance": False,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
