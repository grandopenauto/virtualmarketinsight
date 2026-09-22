from __future__ import annotations

from typing import Any

import api.runtime_v35 as previous
from api.lineage_guard import assert_dispatch_ticket_current
from api.read_only_runner import run_dispatch_ticket

previous.base.VERSION = "0.36.0"
app = previous.app
base = previous.base

_RUN_PATH = "/api/v1/operator/dispatch-tickets/{dispatch_ticket_id}/run-read-only"
app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == _RUN_PATH
        and "POST" in getattr(route, "methods", set())
    )
]


@app.get("/api/v1/operator/lineage-guard/dispatch-tickets/schema")
def operator_dispatch_ticket_freshness_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.lineage-freshness-guard.v5",
        "ticket_must_be_latest_for_execution_authorization": True,
        "enforced_at": ["read_only_runner"],
        "superseded_ticket_reuse_permitted": False,
        "single_use_claim_still_required": True,
        "historical_artifacts_remain_readable": True,
        "external_actions_executed": 0,
    }


@app.post(_RUN_PATH)
def operator_run_read_only_dispatch_ticket_v36(
    dispatch_ticket_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        assert_dispatch_ticket_current(dispatch_ticket_id)
        receipt = run_dispatch_ticket(dispatch_ticket_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.read-only-execution-receipt.v1",
        "receipt": receipt,
        "status": receipt["status"],
        "lineage_freshness_verified": True,
        "internal_read_actions_executed": receipt["internal_read_actions_executed"],
        "external_actions_executed": 0,
    }
