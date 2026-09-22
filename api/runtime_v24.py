from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v23 as previous
from api.lineage_guard import assert_review_record_current
from api.operator_console import SESSION_COOKIE
from api.operator_console_controls import CONSOLE_HTML_V24, csrf_token, validate_csrf
from api.review_events import ReviewEventInput, append_review_event

previous.base.VERSION = "0.24.0"
app = previous.app
base = previous.base

_CONSOLE_PATH = "/operator/console"
_SCHEMA_PATH = "/operator/api/schema"

app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        (getattr(route, "path", None) == _CONSOLE_PATH and "GET" in getattr(route, "methods", set()))
        or (getattr(route, "path", None) == _SCHEMA_PATH and "GET" in getattr(route, "methods", set()))
    )
]


def _session_token(request: Request) -> str:
    previous._require_session(request)
    token = request.cookies.get(SESSION_COOKIE) or ""
    if not token:
        raise base.HTTPException(status_code=401, detail="Operator session required.")
    return token


def _require_csrf(request: Request, supplied: str | None) -> None:
    token = _session_token(request)
    if not validate_csrf(token, supplied):
        raise base.HTTPException(status_code=403, detail="Invalid operator console CSRF token.")


@app.get(_CONSOLE_PATH)
def operator_console_page_v24(request: Request) -> Any:
    if not previous._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return previous._security_headers(HTMLResponse(CONSOLE_HTML_V24))


@app.get("/operator/api/session")
def operator_console_session_info(request: Request) -> dict[str, Any]:
    token = _session_token(request)
    return {
        "schema": "vmi.operator-console-session.v1",
        "csrf_token": csrf_token(token),
        "session_authenticated": True,
        "mutation_scope": "human_review_event_only",
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.post("/operator/api/cases/{record_id}/review-event")
def operator_console_record_review_event(
    request: Request,
    record_id: str,
    event: ReviewEventInput,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    _require_csrf(request, x_vmi_csrf)
    try:
        assert_review_record_current(record_id)
        receipt = append_review_event(record_id, event)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-review-event.v1",
        "event": receipt,
        "state": "review_recorded_no_authority",
        "lineage_freshness_verified": True,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": receipt["next_gate"],
    }


@app.get(_SCHEMA_PATH)
def operator_console_schema_v24(request: Request) -> dict[str, Any]:
    previous._require_session(request)
    return {
        "schema": "vmi.operator-console.v2",
        "authentication": "short-lived Secure HttpOnly operator session",
        "csrf_required_for_mutation": True,
        "enabled_mutations": ["human_review_event_append"],
        "raw_evidence_in_case_view": False,
        "automatic_advancement_permitted": False,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
