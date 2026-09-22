from __future__ import annotations

import json
import sqlite3
from typing import Any

from api.authorizations import verify_authorization_chain
from api.bounded_actions import verify_bounded_action_chain
from api.decision_refresh import verify_decision_refresh_chain
from api.dispatch_tickets import verify_dispatch_ticket_chain
from api.evidence_return import verify_evidence_return_chain
from api.execution_authorizations import verify_execution_authorization_chain
from api.execution_review import verify_execution_review_chain
from api.read_only_runner import verify_execution_receipt_chain
from api.review_events import verify_event_chain
from api.review_ledger import get_record, ledger_path, verify_chain
from api.successor_reviews import verify_successor_reviews

SCHEMA = "vmi.decision-dossier.v1"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone()
    return bool(row)


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _placeholders(values: set[str]) -> str:
    return ",".join("?" for _ in values)


def _review_graph(conn: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, str]]:
    records: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}
    parents: dict[str, str] = {}
    for row in conn.execute("SELECT * FROM review_records ORDER BY sequence ASC").fetchall():
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        cycle = payload.get("review_cycle", {}) or {}
        parent = cycle.get("parent_record_id")
        item["generation"] = int(cycle.get("generation", 0) or 0)
        item["parent_record_id"] = parent
        item["refresh_id"] = cycle.get("decision_refresh_id")
        records[item["record_id"]] = item
        if parent:
            parents[item["record_id"]] = parent
            children.setdefault(parent, []).append(item["record_id"])
    return records, children, parents


def _root(record_id: str, parents: dict[str, str]) -> str:
    current = record_id
    seen: set[str] = set()
    while current in parents:
        if current in seen:
            raise ValueError("review_lineage_cycle_detected")
        seen.add(current)
        current = parents[current]
    return current


def _descendants(root_id: str, children: dict[str, list[str]]) -> set[str]:
    found = {root_id}
    stack = [root_id]
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def _integrity() -> dict[str, Any]:
    checks = {
        "review_ledger": verify_chain(),
        "review_events": verify_event_chain(),
        "bounded_actions": verify_bounded_action_chain(),
        "human_authorizations": verify_authorization_chain(),
        "execution_reviews": verify_execution_review_chain(),
        "execution_authorizations": verify_execution_authorization_chain(),
        "dispatch_tickets": verify_dispatch_ticket_chain(),
        "execution_receipts": verify_execution_receipt_chain(),
        "evidence_returns": verify_evidence_return_chain(),
        "decision_refreshes": verify_decision_refresh_chain(),
        "successor_reviews": verify_successor_reviews(),
    }
    return {
        "ok": all(bool(value.get("ok")) for value in checks.values()),
        "checks": {key: {"ok": bool(value.get("ok")), "checked": value.get("checked")} for key, value in checks.items()},
    }


def build_decision_dossier(record_id: str) -> dict[str, Any]:
    if not get_record(record_id, include_payload=False):
        raise KeyError("review_record_not_found")

    with _connect() as conn:
        records, children, parents = _review_graph(conn)
        root_id = _root(record_id, parents)
        record_ids = _descendants(root_id, children)
        rp = _placeholders(record_ids)
        record_params = tuple(record_ids)

        review_records = [records[rid] for rid in record_ids if rid in records]
        review_records.sort(key=lambda x: x["sequence"])

        events = _rows(conn, f"SELECT sequence,event_id,record_id,created_at,decision,state,payload_sha256,event_receipt_sha256 FROM review_events WHERE record_id IN ({rp}) ORDER BY sequence ASC", record_params) if _table_exists(conn, "review_events") else []
        actions = _rows(conn, f"SELECT sequence,action_packet_id,record_id,event_id,created_at,action_kind,target_capability,state,payload_sha256,packet_receipt_sha256 FROM bounded_action_packets WHERE record_id IN ({rp}) ORDER BY sequence ASC", record_params) if _table_exists(conn, "bounded_action_packets") else []

        action_ids = {row["action_packet_id"] for row in actions}
        authorizations: list[dict[str, Any]] = []
        manifests: list[dict[str, Any]] = []
        tickets: list[dict[str, Any]] = []
        evidence_returns: list[dict[str, Any]] = []
        if action_ids:
            ap = _placeholders(action_ids)
            action_params = tuple(action_ids)
            authorizations = _rows(conn, f"SELECT sequence,authorization_id,action_packet_id,created_at,decision,state,scope_confirmed,payload_sha256,authorization_receipt_sha256 FROM authorization_records WHERE action_packet_id IN ({ap}) ORDER BY sequence ASC", action_params) if _table_exists(conn, "authorization_records") else []
            manifests = _rows(conn, f"SELECT sequence,manifest_id,authorization_id,action_packet_id,created_at,capability_id,contract_id,state,payload_sha256,manifest_receipt_sha256 FROM execution_review_manifests WHERE action_packet_id IN ({ap}) ORDER BY sequence ASC", action_params) if _table_exists(conn, "execution_review_manifests") else []
            tickets = _rows(conn, f"SELECT sequence,dispatch_ticket_id,execution_authorization_id,manifest_id,action_packet_id,created_at,expires_at,capability_id,contract_id,operation,state,payload_sha256,dispatch_ticket_receipt_sha256 FROM dispatch_tickets WHERE action_packet_id IN ({ap}) ORDER BY sequence ASC", action_params) if _table_exists(conn, "dispatch_tickets") else []
            evidence_returns = _rows(conn, f"SELECT sequence,evidence_return_id,execution_receipt_id,dispatch_ticket_id,action_packet_id,record_id,created_at,state,payload_sha256,evidence_return_receipt_sha256 FROM evidence_return_packets WHERE action_packet_id IN ({ap}) ORDER BY sequence ASC", action_params) if _table_exists(conn, "evidence_return_packets") else []

        manifest_ids = {row["manifest_id"] for row in manifests}
        execution_authorizations: list[dict[str, Any]] = []
        if manifest_ids:
            mp = _placeholders(manifest_ids)
            execution_authorizations = _rows(conn, f"SELECT sequence,execution_authorization_id,manifest_id,created_at,expires_at,decision,state,payload_sha256,execution_authorization_receipt_sha256 FROM execution_authorizations WHERE manifest_id IN ({mp}) ORDER BY sequence ASC", tuple(manifest_ids)) if _table_exists(conn, "execution_authorizations") else []

        ticket_ids = {row["dispatch_ticket_id"] for row in tickets}
        execution_receipts: list[dict[str, Any]] = []
        if ticket_ids:
            tp = _placeholders(ticket_ids)
            execution_receipts = _rows(conn, f"SELECT sequence,execution_receipt_id,dispatch_ticket_id,created_at,capability_id,contract_id,operation,status,http_status,result_sha256,payload_sha256,execution_receipt_sha256 FROM read_only_execution_receipts WHERE dispatch_ticket_id IN ({tp}) ORDER BY sequence ASC", tuple(ticket_ids)) if _table_exists(conn, "read_only_execution_receipts") else []

        refreshes = _rows(conn, f"SELECT sequence,refresh_id,evidence_return_id,record_id,prior_packet_id,created_at,state,payload_sha256,refresh_receipt_sha256 FROM decision_refresh_packets WHERE record_id IN ({rp}) ORDER BY sequence ASC", record_params) if _table_exists(conn, "decision_refresh_packets") else []

    timeline: list[dict[str, Any]] = []
    for row in review_records:
        timeline.append({"created_at": row["created_at"], "type": "review_record", "id": row["record_id"], "state": row["state"], "generation": row.get("generation", 0)})
    for row in events:
        timeline.append({"created_at": row["created_at"], "type": "review_event", "id": row["event_id"], "record_id": row["record_id"], "state": row["state"], "decision": row["decision"]})
    for row in actions:
        timeline.append({"created_at": row["created_at"], "type": "bounded_action", "id": row["action_packet_id"], "record_id": row["record_id"], "state": row["state"], "action_kind": row["action_kind"], "target_capability": row["target_capability"]})
    for row in authorizations:
        timeline.append({"created_at": row["created_at"], "type": "human_authorization", "id": row["authorization_id"], "state": row["state"], "decision": row["decision"]})
    for row in manifests:
        timeline.append({"created_at": row["created_at"], "type": "execution_review", "id": row["manifest_id"], "state": row["state"], "capability_id": row["capability_id"], "contract_id": row["contract_id"]})
    for row in execution_authorizations:
        timeline.append({"created_at": row["created_at"], "type": "execution_authorization", "id": row["execution_authorization_id"], "state": row["state"], "decision": row["decision"], "expires_at": row["expires_at"]})
    for row in tickets:
        timeline.append({"created_at": row["created_at"], "type": "dispatch_ticket", "id": row["dispatch_ticket_id"], "state": row["state"], "operation": row["operation"], "expires_at": row["expires_at"]})
    for row in execution_receipts:
        timeline.append({"created_at": row["created_at"], "type": "execution_receipt", "id": row["execution_receipt_id"], "status": row["status"], "operation": row["operation"], "http_status": row["http_status"]})
    for row in evidence_returns:
        timeline.append({"created_at": row["created_at"], "type": "evidence_return", "id": row["evidence_return_id"], "record_id": row["record_id"], "state": row["state"]})
    for row in refreshes:
        timeline.append({"created_at": row["created_at"], "type": "decision_refresh", "id": row["refresh_id"], "record_id": row["record_id"], "state": row["state"]})
    timeline.sort(key=lambda item: item.get("created_at") or "")

    counts = {
        "review_records": len(review_records),
        "review_events": len(events),
        "bounded_actions": len(actions),
        "human_authorizations": len(authorizations),
        "execution_reviews": len(manifests),
        "execution_authorizations": len(execution_authorizations),
        "dispatch_tickets": len(tickets),
        "execution_receipts": len(execution_receipts),
        "evidence_returns": len(evidence_returns),
        "decision_refreshes": len(refreshes),
    }

    return {
        "schema": SCHEMA,
        "requested_record_id": record_id,
        "root_record_id": root_id,
        "review_record_ids": [row["record_id"] for row in review_records],
        "generation_count": max((int(row.get("generation", 0)) for row in review_records), default=0) + 1,
        "counts": counts,
        "artifacts": {
            "review_records": review_records,
            "review_events": events,
            "bounded_actions": actions,
            "human_authorizations": authorizations,
            "execution_reviews": manifests,
            "execution_authorizations": execution_authorizations,
            "dispatch_tickets": tickets,
            "execution_receipts": execution_receipts,
            "evidence_returns": evidence_returns,
            "decision_refreshes": refreshes,
        },
        "timeline": timeline,
        "integrity": _integrity(),
        "authority": {
            "view_only": True,
            "approval_authority": False,
            "execution_authority": False,
            "dispatch_authority": False,
            "external_actions_executed": 0,
        },
    }
