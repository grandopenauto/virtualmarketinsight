from __future__ import annotations

from typing import Any

from api.case_stage import build_case_stage
from api.operator_console import list_operator_cases

_HUMAN_DECISION_STAGES = {"human_review", "human_authorization", "final_authorization", "successor_review"}


def _status(stage: dict[str, Any]) -> str:
    if stage.get("cycle_complete"):
        return "cycle_complete"
    if stage.get("blocking_reason"):
        return "blocked"
    current = (stage.get("current_stage") or {}).get("id")
    if current in _HUMAN_DECISION_STAGES:
        return "needs_human_action"
    if current:
        return "ready_for_operator"
    return "waiting"


def build_attention_queue(limit: int = 50) -> dict[str, Any]:
    cases = list_operator_cases(limit)
    items: list[dict[str, Any]] = []
    priority = {
        "needs_human_action": 0,
        "blocked": 1,
        "ready_for_operator": 2,
        "waiting": 3,
        "cycle_complete": 4,
    }
    for case in cases:
        record_id = str(case["current_record_id"])
        try:
            stage = build_case_stage(record_id)
            status = _status(stage)
            current = stage.get("current_stage") or {}
            items.append(
                {
                    "root_record_id": case.get("root_record_id"),
                    "current_record_id": record_id,
                    "intent_label": case.get("intent_label") or "VMI Review",
                    "query_preview": case.get("query_preview") or "",
                    "generation": case.get("generation", 0),
                    "generation_count": case.get("generation_count", 1),
                    "status": status,
                    "current_stage_id": current.get("id"),
                    "current_stage_label": current.get("label"),
                    "blocking_reason": stage.get("blocking_reason"),
                    "cycle_complete": bool(stage.get("cycle_complete")),
                    "successor_record_id": stage.get("successor_record_id"),
                }
            )
        except (KeyError, ValueError) as exc:
            items.append(
                {
                    "root_record_id": case.get("root_record_id"),
                    "current_record_id": record_id,
                    "intent_label": case.get("intent_label") or "VMI Review",
                    "query_preview": case.get("query_preview") or "",
                    "generation": case.get("generation", 0),
                    "generation_count": case.get("generation_count", 1),
                    "status": "blocked",
                    "current_stage_id": None,
                    "current_stage_label": None,
                    "blocking_reason": str(exc),
                    "cycle_complete": False,
                    "successor_record_id": None,
                }
            )

    items.sort(
        key=lambda x: (
            priority.get(str(x.get("status")), 99),
            -int(x.get("generation", 0) or 0),
            str(x.get("intent_label") or ""),
        )
    )
    counts = {key: 0 for key in priority}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    return {
        "schema": "vmi.case-attention-queue.v1",
        "counts": counts,
        "total": len(items),
        "items": items,
        "ranking_is_operational_only": True,
        "decision_priority_inferred": False,
        "automatic_advancement_permitted": False,
        "authority": {
            "view_only": True,
            "approval_authority": False,
            "execution_authority": False,
            "dispatch_authority": False,
            "external_actions_executed": 0,
        },
    }
