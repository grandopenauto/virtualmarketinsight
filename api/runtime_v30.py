from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v29 as previous
import api.runtime_v23 as session_base
from api.execution_review_context import build_execution_review_context
from api.operator_console_execution_preview import CONSOLE_HTML_V30

previous.base.VERSION = "0.30.0"
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
def operator_console_page_v30(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V30))


@app.get("/operator/api/cases/{record_id}/execution-review-context")
def operator_console_execution_review_context(request: Request, record_id: str) -> dict[str, Any]:
    session_base._require_session(request)
    try:
        return build_execution_review_context(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
