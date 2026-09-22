from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA = "vmi.review-ledger.v1"


def _default_path() -> str:
    root = Path(__file__).resolve().parents[1]
    return str(root / "runtime" / "vmi-review-ledger.sqlite3")


def ledger_path() -> str:
    return os.getenv("VMI_REVIEW_LEDGER_PATH", _default_path())


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    path = Path(ledger_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_records (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            record_type TEXT NOT NULL,
            request_id TEXT,
            packet_id TEXT,
            approval_id TEXT,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_receipt_sha256 TEXT,
            receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    return conn


def append_record(record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    # The ledger records prepared review artifacts only. It is intentionally not
    # an approval store and never converts a prepared artifact into authority.
    if payload.get("state") not in {"prepared_not_approved", None}:
        raise ValueError("ledger_accepts_prepared_records_only")

    payload_sha = _sha256(payload)
    created_at = datetime.now(timezone.utc).isoformat()
    record_id = str(uuid4())

    with _connect() as conn:
        previous = conn.execute(
            "SELECT receipt_sha256 FROM review_records ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["receipt_sha256"] if previous else ""
        receipt_material = {
            "schema": SCHEMA,
            "record_id": record_id,
            "created_at": created_at,
            "record_type": record_type,
            "payload_sha256": payload_sha,
            "previous_receipt_sha256": previous_receipt,
        }
        receipt_sha = _sha256(receipt_material)
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
                record_type,
                payload.get("request_id"),
                payload.get("packet_id"),
                payload.get("approval_id"),
                "prepared_not_approved",
                _canonical(payload),
                payload_sha,
                previous_receipt,
                receipt_sha,
            ),
        )

    return {
        "schema": SCHEMA,
        "record_id": record_id,
        "created_at": created_at,
        "record_type": record_type,
        "request_id": payload.get("request_id"),
        "packet_id": payload.get("packet_id"),
        "approval_id": payload.get("approval_id"),
        "state": "prepared_not_approved",
        "payload_sha256": payload_sha,
        "previous_receipt_sha256": previous_receipt or None,
        "receipt_sha256": receipt_sha,
        "approval_recorded": False,
        "execution_permitted": False,
        "external_actions_executed": 0,
    }


def list_records(limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, record_id, created_at, record_type, request_id,
                   packet_id, approval_id, state, payload_sha256,
                   previous_receipt_sha256, receipt_sha256
            FROM review_records
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_record(record_id: str, include_payload: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM review_records WHERE record_id = ? LIMIT 1", (record_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def verify_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM review_records ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {
                "ok": False,
                "checked": checked,
                "failed_record_id": row["record_id"],
                "reason": "payload_hash_mismatch",
            }
        if (row["previous_receipt_sha256"] or "") != previous_receipt:
            return {
                "ok": False,
                "checked": checked,
                "failed_record_id": row["record_id"],
                "reason": "previous_receipt_mismatch",
            }
        receipt_material = {
            "schema": SCHEMA,
            "record_id": row["record_id"],
            "created_at": row["created_at"],
            "record_type": row["record_type"],
            "payload_sha256": row["payload_sha256"],
            "previous_receipt_sha256": previous_receipt,
        }
        if _sha256(receipt_material) != row["receipt_sha256"]:
            return {
                "ok": False,
                "checked": checked,
                "failed_record_id": row["record_id"],
                "reason": "receipt_hash_mismatch",
            }
        previous_receipt = row["receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_receipt_sha256": previous_receipt or None,
        "approval_authority": False,
        "execution_authority": False,
        "external_actions_executed": 0,
    }
