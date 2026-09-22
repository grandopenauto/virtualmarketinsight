from __future__ import annotations

from typing import Any

from api.governance_monitor import evaluate_governance
from api.operator_console import list_operator_cases

POSTURE_ORDER = {
    "blocked": 0,
    "attention_required": 1,
    "clear_with_history": 2,
    "clear": 3,
}


def build_action_queue(limit: int = 50) -> dict[str, Any]:
    cases = list_operator_cases(limit)
    items: list[dict[str, Any]] = []
    for case in cases:
        current_record_id = str(case["current_record_id"])
        governance = evaluate_governance(current_record_id)
        items.append(
            {
                "root_record_id": case["root_record_id"],
                "current_record_id": current_record_id,
                "intent_label": case.get("intent_label"),
                "query_preview": case.get("query_preview"),
                "generation": case.get("generation"),
                "generation_count": case.get("generation_count"),
                "posture": governance.get("posture"),
                "integrity_ok": governance.get("integrity_ok"),
                "unresolved_gap_count": governance.get("unresolved_gap_count", 0),
                "finding_count": governance.get("finding_count", 0),
                "current_human_gate": governance.get("current_human_gate"),
                "created_at": case.get("created_at"),
            }
        )

    items.sort(
        key=lambda x: (
            POSTURE_ORDER.get(str(x.get("posture")), 9),
            -int(x.get("unresolved_gap_count") or 0),
            str(x.get("created_at") or ""),
        )
    )
    summary = {
        "total": len(items),
        "blocked": sum(1 for x in items if x.get("posture") == "blocked"),
        "attention_required": sum(1 for x in items if x.get("posture") == "attention_required"),
        "clear_with_history": sum(1 for x in items if x.get("posture") == "clear_with_history"),
        "clear": sum(1 for x in items if x.get("posture") == "clear"),
    }
    return {
        "schema": "vmi.operator-action-queue.v1",
        "summary": summary,
        "items": items,
        "ordering_basis": "governance posture, unresolved gaps, then case timestamp",
        "decision_made_for_operator": False,
        "automatic_advancement_permitted": False,
        "authority": {
            "view_only": True,
            "approval_authority": False,
            "execution_authority": False,
            "dispatch_authority": False,
            "external_actions_executed": 0,
        },
    }
