from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import api.app as base
from api.dispatch_tickets import DISPATCHABLE_CONTRACTS, get_dispatch_ticket
from api.execution_authorizations import get_execution_authorization
from api.execution_review import get_execution_review_manifest
from api.review_ledger import ledger_path

SCHEMA = "vmi.read-only-execution-receipt.v1"


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
        CREATE TABLE IF NOT EXISTS dispatch_claims (
            claim_id TEXT PRIMARY KEY,
            dispatch_ticket_id TEXT NOT NULL UNIQUE,
            claimed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS read_only_execution_receipts (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_receipt_id TEXT NOT NULL UNIQUE,
            dispatch_ticket_id TEXT NOT NULL UNIQUE,
            claim_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            status TEXT NOT NULL,
            http_status INTEGER,
            result_json TEXT NOT NULL,
            result_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_execution_receipt_sha256 TEXT,
            execution_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    return conn


def _latest_execution_authorization(manifest_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM execution_authorizations WHERE manifest_id = ? ORDER BY sequence DESC LIMIT 1",
            (manifest_id,),
        ).fetchone()
    return dict(row) if row else None


def _latest_packet_authorization(action_packet_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM authorization_records WHERE action_packet_id = ? ORDER BY sequence DESC LIMIT 1",
            (action_packet_id,),
        ).fetchone()
    return dict(row) if row else None


def _claim_ticket(dispatch_ticket_id: str) -> str:
    claim_id = str(uuid4())
    claimed_at = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO dispatch_claims (claim_id, dispatch_ticket_id, claimed_at) VALUES (?, ?, ?)",
                (claim_id, dispatch_ticket_id, claimed_at),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("dispatch_ticket_already_consumed") from exc
    return claim_id


def _capability_health() -> dict[str, Any]:
    req = Request(
        base.OIE_BASE_URL + "/health",
        headers={"Accept": "application/json", "User-Agent": f"VMI-Runner/{base.VERSION}"},
    )
    try:
        with urlopen(req, timeout=4) as response:
            payload = json.loads(response.read(128_000).decode("utf-8"))
            ok = bool(payload.get("ok")) or str(payload.get("status", "")).lower() in {"ok", "healthy", "ready"}
            return {"ok": ok, "http_status": response.status, "data": base._compact(payload)}
    except HTTPError as exc:
        return {"ok": False, "http_status": exc.code, "error": "upstream_http_error"}
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def _run_oie_read(operation: str, limit: int) -> tuple[int, Any]:
    operation_spec = base.OIE_OPERATIONS.get(operation)
    if not operation_spec:
        raise ValueError("operation_not_present_in_oie_contract")

    url = base.OIE_BASE_URL + operation_spec["path"]
    if operation_spec.get("limit"):
        url += "?" + urlencode({"limit": max(1, min(int(limit), 20))})
    req = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": f"VMI-Runner/{base.VERSION}"},
    )
    with urlopen(req, timeout=8) as response:
        raw = response.read(512_000)
        payload = json.loads(raw.decode("utf-8"))
        return response.status, base._compact(payload)


def _record_execution(
    ticket: dict[str, Any],
    claim_id: str,
    status: str,
    http_status: int | None,
    result: Any,
    health: dict[str, Any],
) -> dict[str, Any]:
    execution_receipt_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    result_sha = _sha256(result)
    payload = {
        "schema": SCHEMA,
        "execution_receipt_id": execution_receipt_id,
        "dispatch_ticket_id": ticket["dispatch_ticket_id"],
        "dispatch_ticket_receipt_sha256": ticket.get("dispatch_ticket_receipt_sha256"),
        "claim_id": claim_id,
        "created_at": created_at,
        "capability_id": ticket["capability_id"],
        "contract_id": ticket["contract_id"],
        "operation": ticket["operation"],
        "status": status,
        "http_status": http_status,
        "capability_health": health,
        "result_sha256": result_sha,
        "authority": {
            "read_only_internal_execution": True,
            "external_write_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "credential_change_permitted": False,
            "internal_read_actions_executed": 1 if status == "completed" else 0,
            "external_actions_executed": 0,
        },
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT execution_receipt_sha256 FROM read_only_execution_receipts ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["execution_receipt_sha256"] if previous else ""
        material = {
            "schema": SCHEMA,
            "execution_receipt_id": execution_receipt_id,
            "dispatch_ticket_id": ticket["dispatch_ticket_id"],
            "claim_id": claim_id,
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_execution_receipt_sha256": previous_receipt,
        }
        receipt = _sha256(material)
        conn.execute(
            """
            INSERT INTO read_only_execution_receipts (
                execution_receipt_id, dispatch_ticket_id, claim_id, created_at,
                capability_id, contract_id, operation, status, http_status,
                result_json, result_sha256, payload_json, payload_sha256,
                previous_execution_receipt_sha256, execution_receipt_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_receipt_id,
                ticket["dispatch_ticket_id"],
                claim_id,
                created_at,
                ticket["capability_id"],
                ticket["contract_id"],
                ticket["operation"],
                status,
                http_status,
                _canonical(result),
                result_sha,
                _canonical(payload),
                payload_sha,
                previous_receipt,
                receipt,
            ),
        )

    return {
        "schema": SCHEMA,
        "execution_receipt_id": execution_receipt_id,
        "dispatch_ticket_id": ticket["dispatch_ticket_id"],
        "claim_id": claim_id,
        "created_at": created_at,
        "capability_id": ticket["capability_id"],
        "contract_id": ticket["contract_id"],
        "operation": ticket["operation"],
        "status": status,
        "http_status": http_status,
        "result": result,
        "result_sha256": result_sha,
        "payload_sha256": payload_sha,
        "previous_execution_receipt_sha256": previous_receipt or None,
        "execution_receipt_sha256": receipt,
        "internal_read_actions_executed": 1 if status == "completed" else 0,
        "external_actions_executed": 0,
    }


def run_dispatch_ticket(dispatch_ticket_id: str) -> dict[str, Any]:
    ticket = get_dispatch_ticket(dispatch_ticket_id, include_payload=True)
    if not ticket:
        raise KeyError("dispatch_ticket_not_found")

    now = datetime.now(timezone.utc)
    if now >= datetime.fromisoformat(ticket["expires_at"]):
        raise ValueError("dispatch_ticket_expired")
    if ticket["contract_id"] not in DISPATCHABLE_CONTRACTS:
        raise ValueError("dispatch_contract_not_allowlisted")
    if ticket["operation"] not in DISPATCHABLE_CONTRACTS[ticket["contract_id"]]:
        raise ValueError("dispatch_operation_not_allowlisted")
    if ticket["capability_id"] != "opportunity-intelligence":
        raise ValueError("runner_capability_not_supported")

    execution_auth = get_execution_authorization(ticket["execution_authorization_id"], include_payload=True)
    if not execution_auth or execution_auth["decision"] != "authorize_read_only_execution":
        raise ValueError("execution_authorization_invalid")
    if now >= datetime.fromisoformat(execution_auth["expires_at"]):
        raise ValueError("execution_authorization_expired")

    manifest = get_execution_review_manifest(ticket["manifest_id"], include_payload=True)
    if not manifest:
        raise KeyError("execution_review_manifest_not_found")

    latest_exec_auth = _latest_execution_authorization(manifest["manifest_id"])
    if not latest_exec_auth or latest_exec_auth["execution_authorization_id"] != ticket["execution_authorization_id"]:
        raise ValueError("execution_authorization_is_not_latest")

    latest_packet_auth = _latest_packet_authorization(manifest["action_packet_id"])
    if not latest_packet_auth or latest_packet_auth["authorization_id"] != manifest["authorization_id"]:
        raise ValueError("packet_authorization_is_not_latest")
    if latest_packet_auth["decision"] != "approve_for_execution_review":
        raise ValueError("packet_authorization_blocks_execution")

    claim_id = _claim_ticket(dispatch_ticket_id)
    health = _capability_health()
    if not health.get("ok"):
        return _record_execution(ticket, claim_id, "failed", health.get("http_status"), {"error": "capability_health_check_failed"}, health)

    plan = ticket["payload"].get("dispatch_plan", {})
    limit = int(plan.get("parameters", {}).get("limit", 5))
    try:
        http_status, result = _run_oie_read(ticket["operation"], limit)
        return _record_execution(ticket, claim_id, "completed", http_status, result, health)
    except HTTPError as exc:
        return _record_execution(ticket, claim_id, "failed", exc.code, {"error": "upstream_http_error"}, health)
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _record_execution(ticket, claim_id, "failed", None, {"error": type(exc).__name__}, health)


def get_execution_receipt(execution_receipt_id: str, include_result: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM read_only_execution_receipts WHERE execution_receipt_id = ? LIMIT 1",
            (execution_receipt_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    if include_result:
        item["result"] = json.loads(item.pop("result_json"))
    else:
        item.pop("result_json", None)
    return item


def list_execution_receipts(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, execution_receipt_id, dispatch_ticket_id, claim_id,
                   created_at, capability_id, contract_id, operation, status,
                   http_status, result_sha256, payload_sha256,
                   previous_execution_receipt_sha256, execution_receipt_sha256
            FROM read_only_execution_receipts
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_execution_receipt_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM read_only_execution_receipts ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        result = json.loads(row["result_json"])
        if _sha256(payload) != row["payload_sha256"] or _sha256(result) != row["result_sha256"]:
            return {"ok": False, "checked": checked, "failed_execution_receipt_id": row["execution_receipt_id"], "reason": "payload_or_result_hash_mismatch"}
        if (row["previous_execution_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_execution_receipt_id": row["execution_receipt_id"], "reason": "previous_receipt_mismatch"}
        material = {
            "schema": SCHEMA,
            "execution_receipt_id": row["execution_receipt_id"],
            "dispatch_ticket_id": row["dispatch_ticket_id"],
            "claim_id": row["claim_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_execution_receipt_sha256": previous_receipt,
        }
        if _sha256(material) != row["execution_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_execution_receipt_id": row["execution_receipt_id"], "reason": "receipt_hash_mismatch"}
        previous_receipt = row["execution_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_execution_receipt_sha256": previous_receipt or None,
        "runner_authority": "read_only_internal_only",
        "external_actions_executed": 0,
    }
