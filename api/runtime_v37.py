from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v36 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.dispatch_tickets import DispatchTicketInput, prepare_dispatch_ticket
from api.execution_authorizations import get_execution_authorization
from api.lineage_guard import assert_execution_review_manifest_current
from api.operator_console_dispatch_ticket import CONSOLE_HTML_V37

previous.base.VERSION = "0.37.0"
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


@app.get(_CONSOLE_PATH)
def operator_console_page_v37(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V37))


@app.post("/operator/api/execution-authorizations/{execution_authorization_id}/dispatch-ticket")
def operator_console_prepare_dispatch_ticket(
    request: Request,
    execution_authorization_id: str,
    payload: DispatchTicketInput,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    try:
        authorization = get_execution_authorization(execution_authorization_id, include_payload=False)
        if not authorization:
            raise KeyError("execution_authorization_not_found")
        assert_execution_review_manifest_current(str(authorization["manifest_id"]))
        ticket = prepare_dispatch_ticket(execution_authorization_id, payload)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-dispatch-ticket.v1",
        "ticket": ticket,
        "state": "prepared_not_dispatched",
        "lineage_freshness_verified": True,
        "dispatch_ready": True,
        "dispatch_executed": False,
        "external_actions_executed": 0,
        "next_gate": ticket["next_gate"],
    }
