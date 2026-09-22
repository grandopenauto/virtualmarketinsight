from __future__ import annotations

from typing import Any

import api.runtime_v17 as previous
from api.successor_reviews import (
    list_successor_reviews,
    prepare_successor_review,
    verify_successor_reviews,
)

previous.base.VERSION = "0.18.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/successor-reviews/schema")
def operator_successor_reviews_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.successor-review-record.v1",
        "purpose": "Start a new immutable review cycle from a decision refresh while preserving lineage and carrying forward evidence but no approval or execution authority.",
        "one_successor_per_refresh": True,
        "same_review_ledger": True,
        "authority_inherited": False,
        "approval_recorded_by_successor": False,
        "execution_permitted_by_successor": False,
        "dispatch_permitted_by_successor": False,
        "external_actions_executed": 0,
    }


@app.post("/api/v1/operator/decision-refreshes/{refresh_id}/successor-review/prepare")
def operator_prepare_successor_review(
    refresh_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        record = prepare_successor_review(refresh_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.successor-review-receipt.v1",
        "record": record,
        "state": "prepared_not_approved",
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "authority_inherited": False,
        "external_actions_executed": 0,
        "next_gate": record["next_gate"],
    }


@app.get("/api/v1/operator/successor-reviews")
def operator_successor_reviews_list(
    limit: int = 50,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    items = list_successor_reviews(limit)
    return {
        "schema": "vmi.successor-review-record.v1",
        "items": items,
        "count": len(items),
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/successor-reviews/verify")
def operator_successor_reviews_verify(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return verify_successor_reviews()
