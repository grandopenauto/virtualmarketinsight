from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import api.runtime_v40 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.decision_refresh import prepare_decision_refresh
from api.decision_refresh_context import build_decision_refresh_context
from api.operator_console_decision_refresh import CONSOLE_HTML_V41

previous.base.VERSION = "0.41.0"
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


class DecisionRefreshConfirmation(BaseModel):
    confirm_decision_refresh: bool = False


@app.get(_CONSOLE_PATH)
def operator_console_page_v41(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V41))


@app.get("/operator/api/cases/{record_id}/decision-refresh-context")
def operator_console_decision_refresh_context(request: Request, record_id: str) -> dict[str, Any]:
    session_base._require_session(request)
    try:
        return build_decision_refresh_context(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))


@app.post("/operator/api/evidence-returns/{evidence_return_id}/decision-refresh")
def operator_console_prepare_decision_refresh(
    request: Request,
    evidence_return_id: str,
    payload: DecisionRefreshConfirmation,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    if payload.confirm_decision_refresh is not True:
        raise base.HTTPException(status_code=409, detail="Explicit decision-refresh confirmation required.")
    try:
        packet = prepare_decision_refresh(evidence_return_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-decision-refresh.v1",
        "packet": packet,
        "state": "refreshed_for_human_review",
        "automatic_gap_resolution_permitted": False,
        "successor_review_created": False,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": packet["next_gate"],
    }
