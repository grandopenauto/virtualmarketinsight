from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ReviewAction = Literal[
    "request_more_evidence",
    "resolve_capability_gap",
    "prepare_bounded_action",
    "stop",
]


class ApprovalEnvelopeInput(BaseModel):
    review_action: ReviewAction
    scope: str = Field(default="", max_length=800)
    rationale: str = Field(default="", max_length=1200)


def build_approval_envelope(
    decision_packet: dict[str, Any],
    approval_input: ApprovalEnvelopeInput,
) -> dict[str, Any]:
    gaps = decision_packet.get("gaps", []) or []
    evidence_state = (
        decision_packet.get("evidence_summary", {}).get("state") or "unknown"
    )

    if approval_input.review_action == "stop":
        readiness = "stop_prepared"
    elif approval_input.review_action == "request_more_evidence":
        readiness = "ready_for_human_review"
    elif approval_input.review_action == "resolve_capability_gap":
        readiness = "ready_for_human_review" if gaps else "no_recorded_gap"
    elif gaps:
        readiness = "needs_gap_review"
    elif evidence_state in {"unavailable", "no_reads"}:
        readiness = "needs_evidence"
    else:
        readiness = "ready_for_human_review"

    return {
        "schema": "vmi.approval-envelope.v1",
        "approval_id": str(uuid4()),
        "packet_id": decision_packet.get("packet_id"),
        "request_id": decision_packet.get("request_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "prepared_not_approved",
        "readiness": readiness,
        "requested_review_action": approval_input.review_action,
        "scope": approval_input.scope,
        "rationale": approval_input.rationale,
        "decision_context": {
            "resolved_surface": decision_packet.get("intent", {}).get("resolved_surface"),
            "execution_graph": decision_packet.get("execution_graph", {}),
            "evidence_state": evidence_state,
            "gap_count": len(gaps),
            "gaps": gaps,
            "prepared_next_action": decision_packet.get("prepared_next_action"),
        },
        "preconditions": [
            {
                "id": "decision_packet_reviewed",
                "required": True,
                "satisfied": False,
                "description": "A human must review the linked Decision Packet.",
            },
            {
                "id": "capability_gaps_reviewed",
                "required": bool(gaps),
                "satisfied": False,
                "description": "Recorded capability/evidence gaps must be reviewed before consequential action.",
            },
            {
                "id": "scope_confirmed",
                "required": approval_input.review_action == "prepare_bounded_action",
                "satisfied": False,
                "description": "Any future action scope must be explicit and bounded.",
            },
        ],
        "required_approvals": [
            {
                "type": "human_operator",
                "required": True,
                "recorded": False,
            },
            {
                "type": "applicable_legal_financial_regulatory_or_professional",
                "required": "conditional",
                "recorded": False,
            },
        ],
        "authority": {
            "approval_recorded": False,
            "self_approval_permitted": False,
            "execution_permitted": False,
            "analysis_generation_permitted": False,
            "capital_movement_permitted": False,
            "trading_permitted": False,
            "outreach_permitted": False,
            "external_actions_executed": 0,
        },
        "next_gate": (
            "Human review and explicit approval recording. This envelope has no execute function."
        ),
    }
