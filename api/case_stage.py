from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.decision_dossiers import build_decision_dossier
from api.lineage_guard import assert_review_record_current
from api.successor_reviews import list_successor_reviews

STAGES = [
    ("human_review", "Human review"),
    ("bounded_action", "Bounded action"),
    ("human_authorization", "Human authorization"),
    ("execution_review", "Execution review manifest"),
    ("final_authorization", "Final read-only authorization"),
    ("dispatch_ticket", "Single-use dispatch ticket"),
    ("read_only_execution", "Read-only execution"),
    ("evidence_return", "Evidence return"),
    ("decision_refresh", "Decision refresh"),
    ("successor_review", "Successor review generation"),
]


def _latest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return max(items, key=lambda x: int(x.get("sequence", 0) or 0))


def build_case_stage(record_id: str) -> dict[str, Any]:
    assert_review_record_current(record_id)
    dossier = build_decision_dossier(record_id)
    artifacts = dossier.get("artifacts", {})

    events = [x for x in artifacts.get("review_events", []) if str(x.get("record_id")) == record_id]
    event = _latest(events)
    actions = [x for x in artifacts.get("bounded_actions", []) if str(x.get("record_id")) == record_id]
    action = _latest(actions)
    action_ids = {str(x.get("action_packet_id")) for x in actions}

    authorizations = [x for x in artifacts.get("authorizations", []) if str(x.get("action_packet_id")) in action_ids]
    authorization = _latest(authorizations)
    manifests = [x for x in artifacts.get("execution_reviews", []) if str(x.get("action_packet_id")) in action_ids]
    manifest = _latest(manifests)
    execution_auths = [x for x in artifacts.get("execution_authorizations", []) if str(x.get("action_packet_id")) in action_ids]
    execution_auth = _latest(execution_auths)
    tickets = [x for x in artifacts.get("dispatch_tickets", []) if str(x.get("action_packet_id")) in action_ids]
    ticket = _latest(tickets)
    ticket_ids = {str(x.get("dispatch_ticket_id")) for x in tickets}
    executions = [x for x in artifacts.get("execution_receipts", []) if str(x.get("dispatch_ticket_id")) in ticket_ids]
    execution = _latest(executions)
    evidence_returns = [x for x in artifacts.get("evidence_returns", []) if str(x.get("record_id")) == record_id]
    evidence_return = _latest(evidence_returns)
    refreshes = [x for x in artifacts.get("decision_refreshes", []) if str(x.get("record_id")) == record_id]
    refresh = _latest(refreshes)
    successor = next(
        (x for x in list_successor_reviews(100) if str(x.get("parent_record_id")) == record_id),
        None,
    )

    exists = [
        bool(event),
        bool(action),
        bool(authorization and authorization.get("decision") == "approve_for_execution_review"),
        bool(manifest),
        bool(execution_auth and execution_auth.get("decision") == "authorize_read_only_execution"),
        bool(ticket),
        bool(execution and execution.get("status") == "completed"),
        bool(evidence_return),
        bool(refresh),
        bool(successor),
    ]

    blocking_reason: str | None = None
    if event and event.get("decision") == "stop":
        blocking_reason = "review_stopped"
    elif authorization and authorization.get("decision") in {"request_changes", "hold", "reject"}:
        blocking_reason = f"human_authorization_{authorization.get('decision')}"
    elif execution_auth and execution_auth.get("decision") in {"request_changes", "hold", "reject"}:
        blocking_reason = f"final_authorization_{execution_auth.get('decision')}"
    elif ticket:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(str(ticket.get("expires_at"))):
                if not execution:
                    blocking_reason = "dispatch_ticket_expired"
        except (TypeError, ValueError):
            blocking_reason = "dispatch_ticket_expiry_invalid"

    if successor:
        current_index = None
    elif blocking_reason:
        if blocking_reason.startswith("human_authorization_"):
            current_index = 2
        elif blocking_reason.startswith("final_authorization_"):
            current_index = 4
        elif blocking_reason.startswith("dispatch_ticket_"):
            current_index = 5
        else:
            current_index = 0
    else:
        current_index = next((i for i, present in enumerate(exists) if not present), None)

    stages: list[dict[str, Any]] = []
    for i, (stage_id, label) in enumerate(STAGES):
        if successor:
            state = "complete"
        elif current_index is None:
            state = "complete" if exists[i] else "locked"
        elif i < current_index and exists[i]:
            state = "complete"
        elif i == current_index:
            state = "current"
        else:
            state = "locked"
        stages.append({"id": stage_id, "label": label, "state": state})

    current_stage = stages[current_index] if current_index is not None else None
    return {
        "schema": "vmi.case-stage.v1",
        "record_id": record_id,
        "root_record_id": dossier.get("root_record_id"),
        "generation_count": dossier.get("generation_count", 0),
        "stages": stages,
        "current_stage": current_stage,
        "blocking_reason": blocking_reason,
        "cycle_complete": bool(successor),
        "successor_record_id": successor.get("record_id") if successor else None,
        "automatic_advancement_permitted": False,
        "decision_made_for_operator": False,
        "authority": {
            "view_only": True,
            "approval_authority": False,
            "execution_authority": False,
            "dispatch_authority": False,
            "external_actions_executed": 0,
        },
    }
