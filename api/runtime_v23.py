from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import api.runtime_v22 as previous
from api.operator_console import (
    CONSOLE_HTML,
    LOGIN_HTML,
    OperatorLogin,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    build_console_case,
    issue_session_token,
    list_operator_cases,
    validate_session_token,
)

previous.base.VERSION = "0.23.0"
app = previous.app
base = previous.base


def _security_headers(response: Any) -> Any:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


def _has_session(request: Request) -> bool:
    return validate_session_token(request.cookies.get(SESSION_COOKIE))


def _require_session(request: Request) -> None:
    if not _has_session(request):
        raise base.HTTPException(status_code=401, detail="Operator session required.")


@app.get("/operator")
def operator_root(request: Request) -> Any:
    return RedirectResponse("/operator/console" if _has_session(request) else "/operator/login", status_code=303)


@app.get("/operator/login")
def operator_login_page(request: Request) -> Any:
    if _has_session(request):
        return RedirectResponse("/operator/console", status_code=303)
    return _security_headers(HTMLResponse(LOGIN_HTML))


@app.post("/operator/session")
def operator_create_session(payload: OperatorLogin) -> Any:
    try:
        base._require_operator_key(payload.operator_key)
    except Exception:
        return _security_headers(JSONResponse({"ok": False, "detail": "Access denied."}, status_code=401))
    token = issue_session_token(secret=payload.operator_key)
    response = JSONResponse({"ok": True, "session": "created", "expires_in_seconds": SESSION_TTL_SECONDS})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/operator",
    )
    return _security_headers(response)


@app.delete("/operator/session")
def operator_delete_session() -> Any:
    response = JSONResponse({"ok": True, "session": "cleared"})
    response.delete_cookie(SESSION_COOKIE, path="/operator", secure=True, httponly=True, samesite="strict")
    return _security_headers(response)


@app.get("/operator/console")
def operator_console_page(request: Request) -> Any:
    if not _has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return _security_headers(HTMLResponse(CONSOLE_HTML))


@app.get("/operator/api/cases")
def operator_console_cases(request: Request, limit: int = 50) -> dict[str, Any]:
    _require_session(request)
    items = list_operator_cases(limit)
    return {
        "schema": "vmi.operator-console-cases.v1",
        "items": items,
        "count": len(items),
        "console_view_only": True,
        "automatic_advancement_permitted": False,
        "external_actions_executed": 0,
    }


@app.get("/operator/api/cases/{record_id}")
def operator_console_case(request: Request, record_id: str) -> dict[str, Any]:
    _require_session(request)
    try:
        return build_console_case(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))


@app.get("/operator/api/schema")
def operator_console_schema(request: Request) -> dict[str, Any]:
    _require_session(request)
    return {
        "schema": "vmi.operator-console.v1",
        "authentication": "short-lived Secure HttpOnly operator session",
        "session_ttl_seconds": SESSION_TTL_SECONDS,
        "raw_evidence_in_case_view": False,
        "mutation_controls_enabled": False,
        "console_view_only": True,
        "automatic_advancement_permitted": False,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }
