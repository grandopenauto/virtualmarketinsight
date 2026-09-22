from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import api.runtime_v38 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.lineage_guard import assert_dispatch_ticket_current
from api.operator_console_runner_control import CONSOLE_HTML_V39
from api.read_only_runner import run_dispatch_ticket

previous.base.VERSION = "0.39.0"
app = previous.app
base = previous.base

_CONSOLE_PATH = "/operator/console"
app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == _CONSOLE_PATH
        and "GET" in getattr(route, "methods", set())
    )
]


class RunnerConfirmation(BaseModel):
    confirm_single_use_read_only: bool = False


def _safe_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "execution_receipt_id",
        "dispatch_ticket_id",
        "claim_id",
        "created_at",
        "capability_id",
        "contract_id",
        "operation",
        "status",
        "http_status",
        "result_sha256",
        "payload_sha256",
        "previous_execution_receipt_sha256",
        "execution_receipt_sha256",
        "internal_read_actions_executed",
        "external_actions_executed",
    )
    return {key: receipt.get(key) for key in allowed}


@app.get(_CONSOLE_PATH)
def operator_console_page_v39(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V39))


@app.post("/operator/api/dispatch-tickets/{dispatch_ticket_id}/run-read-only")
def operator_console_run_read_only(
    request: Request,
    dispatch_ticket_id: str,
    payload: RunnerConfirmation,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    if payload.confirm_single_use_read_only is not True:
        raise base.HTTPException(
            status_code=409,
            detail="Explicit single-use read-only execution confirmation required.",
        )
    try:
        assert_dispatch_ticket_current(dispatch_ticket_id)
        receipt = run_dispatch_ticket(dispatch_ticket_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-read-only-execution.v1",
        "receipt": _safe_receipt(receipt),
        "raw_result_exposed": False,
        "evidence_return_created": False,
        "decision_refresh_created": False,
        "successor_review_created": False,
        "lineage_freshness_verified": True,
        "external_actions_executed": 0,
        "next_gate": "Explicitly return the execution result as evidence. No evidence return or new review cycle is created automatically.",
    }
