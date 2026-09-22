from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from api.decision_dossiers import build_decision_dossier
from api.review_ledger import get_record

SCHEMA = "vmi.governance-monitor.v1"


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _latest_by(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in items:
        value = str(item.get(key) or "")
        if value:
            latest[value] = item
    return latest


def evaluate_governance(record_id: str) -> dict[str, Any]:
    dossier = build_decision_dossier(record_id)
    now = datetime.now(timezone.utc)
    artifacts = dossier["artifacts"]
    findings: list[dict[str, Any]] = []

    if not dossier["integrity"].get("ok"):
        findings.append({"severity": "block", "code": "chain_integrity_failure", "detail": "At least one append-only chain failed verification."})

    authorizations = artifacts.get("human_authorizations", [])
    latest_packet_auth = _latest_by(authorizations, "action_packet_id")
    manifests = artifacts.get("execution_reviews", [])
    for manifest in manifests:
        latest = latest_packet_auth.get(str(manifest.get("action_packet_id") or ""))
        if latest and latest.get("authorization_id") != manifest.get("authorization_id"):
            findings.append({
                "severity": "attention",
                "code": "stale_execution_review_manifest",
                "artifact_id": manifest.get("manifest_id"),
                "detail": "The manifest was created from an authorization that is no longer latest for its bounded action packet.",
            })

    execution_authorizations = artifacts.get("execution_authorizations", [])
    latest_exec_auth = _latest_by(execution_authorizations, "manifest_id")
    for auth in latest_exec_auth.values():
        expiry = _dt(auth.get("expires_at"))
        if auth.get("decision") == "authorize_read_only_execution" and expiry and now >= expiry:
            findings.append({
                "severity": "info",
                "code": "execution_authorization_expired",
                "artifact_id": auth.get("execution_authorization_id"),
                "detail": "A previously issued read-only execution authorization has expired and cannot be reused.",
            })

    receipts_by_ticket = {str(item.get("dispatch_ticket_id")): item for item in artifacts.get("execution_receipts", [])}
    for ticket in artifacts.get("dispatch_tickets", []):
        ticket_id = str(ticket.get("dispatch_ticket_id") or "")
        expiry = _dt(ticket.get("expires_at"))
        if ticket_id in receipts_by_ticket:
            continue
        if expiry and now >= expiry:
            findings.append({
                "severity": "info",
                "code": "dispatch_ticket_expired_unconsumed",
                "artifact_id": ticket_id,
                "detail": "A prepared dispatch ticket expired without execution and would require a new authorization path.",
            })
        else:
            findings.append({
                "severity": "attention",
                "code": "dispatch_ticket_active_unconsumed",
                "artifact_id": ticket_id,
                "detail": "A short-lived dispatch ticket is prepared and has not been consumed.",
            })

    refresh_by_return = {str(item.get("evidence_return_id")): item for item in artifacts.get("decision_refreshes", [])}
    for returned in artifacts.get("evidence_returns", []):
        return_id = str(returned.get("evidence_return_id") or "")
        if return_id not in refresh_by_return:
            findings.append({
                "severity": "attention",
                "code": "evidence_return_awaiting_refresh",
                "artifact_id": return_id,
                "detail": "Returned evidence has not yet been incorporated into a decision refresh.",
            })

    refresh_ids_with_successor: set[str] = set()
    review_records = artifacts.get("review_records", [])
    for item in review_records:
        if item.get("refresh_id"):
            refresh_ids_with_successor.add(str(item.get("refresh_id")))
    for refresh in artifacts.get("decision_refreshes", []):
        refresh_id = str(refresh.get("refresh_id") or "")
        if refresh_id not in refresh_ids_with_successor:
            findings.append({
                "severity": "attention",
                "code": "decision_refresh_awaiting_successor_review",
                "artifact_id": refresh_id,
                "detail": "A refreshed decision snapshot has not yet opened a successor review cycle.",
            })

    record_ids_with_events = {str(item.get("record_id")) for item in artifacts.get("review_events", [])}
    for review in review_records:
        if int(review.get("generation", 0) or 0) > 0 and str(review.get("record_id")) not in record_ids_with_events:
            findings.append({
                "severity": "attention",
                "code": "successor_review_awaiting_human_event",
                "artifact_id": review.get("record_id"),
                "detail": "A successor review cycle exists but has not yet received a human review event.",
            })

    latest_review = max(review_records, key=lambda x: int(x.get("sequence", 0)), default=None)
    unresolved_gap_count = 0
    current_gate = "No review record available."
    if latest_review:
        full = get_record(str(latest_review["record_id"]), include_payload=True)
        if full:
            payload = full.get("payload", {})
            packet = payload.get("decision_packet", {}) or {}
            unresolved_gap_count = len(packet.get("gaps", []) or [])
            current_gate = str(payload.get("next_gate") or packet.get("next_gate") or "Human review required.")

    latest_events_by_record = _latest_by(artifacts.get("review_events", []), "record_id")
    if latest_review:
        latest_event = latest_events_by_record.get(str(latest_review.get("record_id")))
        if latest_event:
            decision = latest_event.get("decision")
            current_gate = {
                "request_more_evidence": "Prepare a new bounded evidence action for human review; no automatic execution.",
                "resolve_capability_gap": "Document or resolve the selected capability gap before further consequential preparation.",
                "prepare_bounded_action": "Prepare a new bounded action packet, then require a separate human authorization.",
                "stop": "Review path stopped. No further action is authorized.",
            }.get(str(decision), current_gate)

    if unresolved_gap_count:
        findings.append({
            "severity": "info",
            "code": "unresolved_gaps_present",
            "count": unresolved_gap_count,
            "detail": "The latest review cycle still carries unresolved gaps; returned evidence does not resolve them automatically.",
        })

    severity_rank = {"info": 1, "attention": 2, "block": 3}
    highest = max((severity_rank.get(item["severity"], 0) for item in findings), default=0)
    posture = {0: "clear", 1: "clear_with_history", 2: "attention_required", 3: "blocked"}[highest]

    return {
        "schema": SCHEMA,
        "record_id": record_id,
        "root_record_id": dossier["root_record_id"],
        "evaluated_at": now.isoformat(),
        "posture": posture,
        "generation_count": dossier["generation_count"],
        "unresolved_gap_count": unresolved_gap_count,
        "current_human_gate": current_gate,
        "findings": findings,
        "finding_count": len(findings),
        "integrity_ok": bool(dossier["integrity"].get("ok")),
        "authority": {
            "monitor_only": True,
            "automatic_advancement_permitted": False,
            "approval_authority": False,
            "execution_authority": False,
            "dispatch_authority": False,
            "external_actions_executed": 0,
        },
    }
