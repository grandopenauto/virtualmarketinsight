from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v27 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.action_context import build_action_context
from api.bounded_actions import BoundedActionInput, prepare_bounded_action
from api.lineage_guard import assert_review_event_current
from api.operator_console_bounded import CONSOLE_HTML_V28

previous.base.VERSION = "0.28.0"
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
def operator_console_page_v28(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V28))


@app.get("/operator/api/cases/{record_id}/action-context")
def operator_console_action_context(request: Request, record_id: str) -> dict[str, Any]:
    session_base._require_session(request)
    try:
        return build_action_context(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))


@app.post("/operator/api/review-events/{event_id}/bounded-action")
def operator_console_prepare_bounded_action(
    request: Request,
    event_id: str,
    payload: BoundedActionInput,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    try:
        assert_review_event_current(event_id)
        packet = prepare_bounded_action(event_id, payload)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-bounded-action.v1",
        "packet": packet,
        "state": "prepared_not_approved",
        "lineage_freshness_verified": True,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": packet["next_gate"],
    }
