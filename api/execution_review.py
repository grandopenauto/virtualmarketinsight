from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from api.bounded_actions import get_bounded_action
from api.review_ledger import ledger_path

SCHEMA = "vmi.execution-review-manifest.v1"


class ExecutionReviewInput(BaseModel):
    reviewer_label: str = Field(default="operator", max_length=120)
    purpose: str = Field(default="", max_length=1200)


CONTRACT_REGISTRY: dict[str, dict[str, Any]] = {
    "opportunity intelligence": {
        "capability_id": "opportunity-intelligence",
        "contract_id": "oie.read-research.v1",
        "transport": "internal adapter registry",
        "allowed_action_kinds": {"research_only", "evidence_refresh"},
        "operations": ["opportunities", "demand_status", "demand_matches"],
        "effect_class": "read_only_internal",
    },
    "business analyst": {
        "capability_id": "business-analyst-vmi-read",
        "contract_id": "business-analyst.vmi-read.v1",
        "transport": "loopback-only read sidecar",
        "allowed_action_kinds": {"research_only", "internal_analysis_preparation", "capability_gap_resolution"},
        "operations": ["allowlisted_native_reads"],
        "effect_class": "read_only_internal",
    },
}


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
        CREATE TABLE IF NOT EXISTS execution_review_manifests (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            manifest_id TEXT NOT NULL UNIQUE,
            authorization_id TEXT NOT NULL,
            action_packet_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_manifest_receipt_sha256 TEXT,
            manifest_receipt_sha256 TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_execution_review_packet ON execution_review_manifests(action_packet_id, sequence)"
    )
    return conn


def _authorization(authorization_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM authorization_records WHERE authorization_id = ? LIMIT 1",
            (authorization_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def _latest_authorization(action_packet_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM authorization_records WHERE action_packet_id = ? ORDER BY sequence DESC LIMIT 1",
            (action_packet_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def prepare_execution_review_manifest(
    authorization_id: str, request: ExecutionReviewInput
) -> dict[str, Any]:
    authorization = _authorization(authorization_id)
    if not authorization:
        raise KeyError("authorization_not_found")

    if authorization["decision"] != "approve_for_execution_review":
        raise ValueError("authorization_not_approved_for_execution_review")

    latest = _latest_authorization(authorization["action_packet_id"])
    if not latest or latest["authorization_id"] != authorization_id:
        raise ValueError("authorization_is_not_latest_for_packet")

    packet = get_bounded_action(authorization["action_packet_id"], include_payload=True)
    if not packet:
        raise KeyError("bounded_action_packet_not_found")

    capability_name = (packet.get("target_capability") or "").strip().lower()
    contract = CONTRACT_REGISTRY.get(capability_name)
    if not contract:
        raise ValueError("target_capability_contract_not_allowlisted")
    if packet["action_kind"] not in contract["allowed_action_kinds"]:
        raise ValueError("action_kind_not_allowed_by_capability_contract")

    manifest_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": SCHEMA,
        "manifest_id": manifest_id,
        "authorization_id": authorization_id,
        "authorization_receipt_sha256": authorization.get("authorization_receipt_sha256"),
        "action_packet_id": packet["action_packet_id"],
        "action_packet_receipt_sha256": packet.get("packet_receipt_sha256"),
        "created_at": created_at,
        "state": "execution_review_prepared",
        "reviewer_label": request.reviewer_label.strip() or "operator",
        "purpose": request.purpose,
        "proposed_execution": {
            "capability_id": contract["capability_id"],
            "contract_id": contract["contract_id"],
            "transport": contract["transport"],
            "effect_class": contract["effect_class"],
            "action_kind": packet["action_kind"],
            "objective": packet["objective"],
            "scope": packet["scope"],
            "operations": contract["operations"],
            "payload_shape": {
                "objective": "string",
                "scope": "string",
                "source_action_packet_id": "uuid",
                "source_authorization_id": "uuid",
            },
        },
        "permitted_effects": [
            "bounded internal read-only evidence retrieval",
            "prepare internal research or review artifacts",
        ],
        "prohibited_effects": [
            "external outreach",
            "capital movement",
            "trading or securities transactions",
            "purchases or payment initiation",
            "credential or permission changes",
            "arbitrary URL or path execution",
            "external system writes",
            "automatic dispatch",
            "self-approval",
        ],
        "preconditions": [
            {"id": "authorization_is_latest", "required": True, "satisfied": True},
            {"id": "capability_contract_allowlisted", "required": True, "satisfied": True},
            {"id": "capability_health_rechecked_at_execution", "required": True, "satisfied": False},
            {"id": "final_execution_authorization", "required": True, "satisfied": False},
        ],
        "authority": {
            "human_execution_review_approval_recorded": True,
            "execution_permitted": False,
            "dispatch_permitted": False,
            "external_write_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": "Final capability-specific execution authorization. This manifest cannot dispatch or execute.",
    }
    payload_sha = _sha256(payload)

    with _connect() as conn:
        previous = conn.execute(
            "SELECT manifest_receipt_sha256 FROM execution_review_manifests ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_receipt = previous["manifest_receipt_sha256"] if previous else ""
        receipt_material = {
            "schema": SCHEMA,
            "manifest_id": manifest_id,
            "authorization_id": authorization_id,
            "action_packet_id": packet["action_packet_id"],
            "created_at": created_at,
            "payload_sha256": payload_sha,
            "previous_manifest_receipt_sha256": previous_receipt,
        }
        manifest_receipt = _sha256(receipt_material)
        conn.execute(
            """
            INSERT INTO execution_review_manifests (
                manifest_id, authorization_id, action_packet_id, created_at,
                capability_id, contract_id, state, payload_json, payload_sha256,
                previous_manifest_receipt_sha256, manifest_receipt_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                manifest_id,
                authorization_id,
                packet["action_packet_id"],
                created_at,
                contract["capability_id"],
                contract["contract_id"],
                "execution_review_prepared",
                _canonical(payload),
                payload_sha,
                previous_receipt,
                manifest_receipt,
            ),
        )

    return {
        "schema": SCHEMA,
        "manifest_id": manifest_id,
        "authorization_id": authorization_id,
        "action_packet_id": packet["action_packet_id"],
        "created_at": created_at,
        "capability_id": contract["capability_id"],
        "contract_id": contract["contract_id"],
        "state": "execution_review_prepared",
        "payload_sha256": payload_sha,
        "previous_manifest_receipt_sha256": previous_receipt or None,
        "manifest_receipt_sha256": manifest_receipt,
        "approval_recorded": True,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": payload["next_gate"],
    }


def get_execution_review_manifest(manifest_id: str, include_payload: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM execution_review_manifests WHERE manifest_id = ? LIMIT 1",
            (manifest_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if include_payload:
        item["payload"] = json.loads(item.pop("payload_json"))
    else:
        item.pop("payload_json", None)
    return item


def list_execution_review_manifests(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sequence, manifest_id, authorization_id, action_packet_id,
                   created_at, capability_id, contract_id, state, payload_sha256,
                   previous_manifest_receipt_sha256, manifest_receipt_sha256
            FROM execution_review_manifests
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_execution_review_chain() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM execution_review_manifests ORDER BY sequence ASC"
        ).fetchall()

    previous_receipt = ""
    checked = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if _sha256(payload) != row["payload_sha256"]:
            return {"ok": False, "checked": checked, "failed_manifest_id": row["manifest_id"], "reason": "payload_hash_mismatch"}
        if (row["previous_manifest_receipt_sha256"] or "") != previous_receipt:
            return {"ok": False, "checked": checked, "failed_manifest_id": row["manifest_id"], "reason": "previous_manifest_receipt_mismatch"}
        material = {
            "schema": SCHEMA,
            "manifest_id": row["manifest_id"],
            "authorization_id": row["authorization_id"],
            "action_packet_id": row["action_packet_id"],
            "created_at": row["created_at"],
            "payload_sha256": row["payload_sha256"],
            "previous_manifest_receipt_sha256": previous_receipt,
        }
        if _sha256(material) != row["manifest_receipt_sha256"]:
            return {"ok": False, "checked": checked, "failed_manifest_id": row["manifest_id"], "reason": "manifest_receipt_hash_mismatch"}
        previous_receipt = row["manifest_receipt_sha256"]
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "head_manifest_receipt_sha256": previous_receipt or None,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
