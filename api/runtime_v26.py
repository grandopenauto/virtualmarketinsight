from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v25 as previous
import api.runtime_v23 as session_base
from api.action_queue import build_action_queue
from api.operator_console_queue import CONSOLE_HTML_V26

previous.base.VERSION = "0.26.0"
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
def operator_console_page_v26(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V26))


@app.get("/operator/api/action-queue")
def operator_console_action_queue(request: Request, limit: int = 50) -> dict[str, Any]:
    session_base._require_session(request)
    return build_action_queue(limit)
