from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _provider_summary(brief: dict[str, Any]) -> dict[str, Any]:
    evidence = brief.get("evidence", {})
    oie_items = evidence.get("opportunity_intelligence", {}).get("items", []) or []
    ba_items = evidence.get("business_analyst_native", {}).get("items", []) or []

    oie_ok = sum(1 for item in oie_items if item.get("ok"))
    ba_ok = sum(1 for item in ba_items if item.get("ok"))

    return {
        "opportunity_intelligence": {
            "available": oie_ok > 0,
            "successful_reads": oie_ok,
            "attempted_reads": len(oie_items),
            "operations": [
                {
                    "operation": item.get("operation"),
                    "ok": bool(item.get("ok")),
                    "status": item.get("status"),
                    "error": item.get("error"),
                }
                for item in oie_items
            ],
        },
        "business_analyst_native": {
            "available": ba_ok > 0,
            "successful_reads": ba_ok,
            "attempted_reads": len(ba_items),
            "reads": [
                {
                    "agent_id": item.get("agent_id"),
                    "surface": item.get("surface"),
                    "ok": bool(item.get("ok")),
                    "status": item.get("status"),
                    "error": item.get("error"),
                }
                for item in ba_items
            ],
        },
    }


def _gaps(brief: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []

    for item in brief.get("capability_health", []) or []:
        if not item.get("reachable"):
            gaps.append(
                {
                    "type": "capability_unavailable",
                    "capability": str(item.get("label") or item.get("id") or "unknown"),
                    "detail": str(item.get("error") or "health check unavailable"),
                }
            )

    ba_items = (
        brief.get("evidence", {})
        .get("business_analyst_native", {})
        .get("items", [])
        or []
    )
    for item in ba_items:
        if not item.get("ok"):
            gaps.append(
                {
                    "type": "native_read_unavailable",
                    "capability": str(item.get("agent_id") or "unknown"),
                    "detail": f"surface={item.get('surface') or 'unknown'} status={item.get('status') or 'unavailable'}",
                }
            )

    oie_items = (
        brief.get("evidence", {})
        .get("opportunity_intelligence", {})
        .get("items", [])
        or []
    )
    for item in oie_items:
        if not item.get("ok"):
            gaps.append(
                {
                    "type": "evidence_read_unavailable",
                    "capability": "Opportunity Intelligence Engine",
                    "detail": f"operation={item.get('operation') or 'unknown'} status={item.get('status') or item.get('error') or 'unavailable'}",
                }
            )

    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for gap in gaps:
        key = (gap["type"], gap["capability"], gap["detail"])
        if key not in seen:
            unique.append(gap)
            seen.add(key)
    return unique[:30]


def build_decision_packet(request: Any, brief: dict[str, Any]) -> dict[str, Any]:
    route = brief.get("route", {})
    provider_summary = _provider_summary(brief)
    gaps = _gaps(brief)

    provider_attempts = sum(
        int(provider.get("attempted_reads", 0)) for provider in provider_summary.values()
    )
    provider_successes = sum(
        int(provider.get("successful_reads", 0)) for provider in provider_summary.values()
    )

    if provider_attempts == 0:
        evidence_state = "no_reads"
    elif provider_successes == provider_attempts:
        evidence_state = "all_attempted_reads_succeeded"
    elif provider_successes > 0:
        evidence_state = "partial"
    else:
        evidence_state = "unavailable"

    return {
        "schema": "vmi.decision-packet.v1",
        "packet_id": str(uuid4()),
        "request_id": brief.get("request_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "intent": {
            "query": getattr(request, "query", ""),
            "starting_surface": getattr(request, "starting_surface", None),
            "resolved_surface": route.get("resolved_surface"),
            "label": route.get("label"),
            "match_level": route.get("match_level"),
            "signals": route.get("signals", []),
        },
        "execution_graph": {
            "path": route.get("graph_path", []),
            "current_state": "evidence_and_planning",
        },
        "capability_plan": route.get("capability_plan", []),
        "capability_health": brief.get("capability_health", []),
        "evidence": brief.get("evidence", {}),
        "evidence_summary": {
            "state": evidence_state,
            "successful_reads": provider_successes,
            "attempted_reads": provider_attempts,
            "providers": provider_summary,
        },
        "gaps": gaps,
        "prepared_next_action": route.get("next_action"),
        "authority": {
            "mode": "analysis_and_evidence_only",
            "human_review_required": True,
            "external_execution_permitted": False,
            "analysis_generation_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "approval_gates": [
            "Human review of evidence and capability gaps.",
            "Explicit approval before any external or consequential action.",
            "Applicable legal, financial, regulatory, mandate or professional approval before capital or regulated activity.",
        ],
        "review_options": [
            "request_more_evidence",
            "resolve_capability_gap",
            "prepare_bounded_action",
            "stop",
        ],
        "next_gate": "Human review. No execution is triggered by creating this packet.",
    }
