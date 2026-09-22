from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v24 as previous
from api.capability_readiness import capability_readiness
from api.operator_console_readiness import CONSOLE_HTML_V25

previous.base.VERSION = "0.25.0"
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
def operator_console_page_v25(request: Request) -> Any:
    if not previous.previous._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return previous.previous._security_headers(HTMLResponse(CONSOLE_HTML_V25))


@app.get("/operator/api/capabilities")
def operator_console_capabilities(request: Request) -> dict[str, Any]:
    previous.previous._require_session(request)
    return capability_readiness(base)
