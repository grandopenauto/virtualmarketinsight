from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import api.runtime_v41 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.operator_console_successor_review import CONSOLE_HTML_V42
from api.successor_review_context import build_successor_review_context
from api.successor_reviews import prepare_successor_review

previous.base.VERSION = "0.42.0"
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


class SuccessorReviewConfirmation(BaseModel):
    confirm_successor_review: bool = False


@app.get(_CONSOLE_PATH)
def operator_console_page_v42(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V42))


@app.get("/operator/api/cases/{record_id}/successor-review-context")
def operator_console_successor_review_context(request: Request, record_id: str) -> dict[str, Any]:
    session_base._require_session(request)
    try:
        return build_successor_review_context(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))


@app.post("/operator/api/decision-refreshes/{refresh_id}/successor-review")
def operator_console_prepare_successor_review(
    request: Request,
    refresh_id: str,
    payload: SuccessorReviewConfirmation,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    if payload.confirm_successor_review is not True:
        raise base.HTTPException(status_code=409, detail="Explicit successor-review confirmation required.")
    try:
        successor = prepare_successor_review(refresh_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-successor-review.v1",
        "successor": successor,
        "state": "prepared_not_approved",
        "authority_inherited": False,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": successor["next_gate"],
    }
