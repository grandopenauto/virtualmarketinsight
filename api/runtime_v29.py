from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v28 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.authorization_context import build_authorization_context
from api.authorizations import AuthorizationInput, append_authorization
from api.lineage_guard import assert_action_packet_current
from api.operator_console_authorization import CONSOLE_HTML_V29

previous.base.VERSION = "0.29.0"
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
def operator_console_page_v29(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V29))


@app.get("/operator/api/cases/{record_id}/authorization-context")
def operator_console_authorization_context(request: Request, record_id: str) -> dict[str, Any]:
    session_base._require_session(request)
    try:
        return build_authorization_context(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))


@app.post("/operator/api/bounded-actions/{action_packet_id}/authorization")
def operator_console_record_authorization(
    request: Request,
    action_packet_id: str,
    payload: AuthorizationInput,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    try:
        assert_action_packet_current(action_packet_id)
        authorization = append_authorization(action_packet_id, payload)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-authorization.v1",
        "authorization": authorization,
        "lineage_freshness_verified": True,
        "approval_recorded": authorization["approval_recorded"],
        "approval_scope": authorization["approval_scope"],
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": authorization["next_gate"],
    }
