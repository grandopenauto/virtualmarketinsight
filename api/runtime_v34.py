from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v33 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.capability_readiness import capability_readiness
from api.execution_authorizations import ExecutionAuthorizationInput, append_execution_authorization
from api.execution_review import get_execution_review_manifest
from api.lineage_guard import assert_execution_review_manifest_current
from api.operator_console_final_authorization import CONSOLE_HTML_V34

previous.base.VERSION = "0.34.0"
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
def operator_console_page_v34(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V34))


@app.post("/operator/api/execution-reviews/{manifest_id}/final-authorization")
def operator_console_final_execution_authorization(
    request: Request,
    manifest_id: str,
    payload: ExecutionAuthorizationInput,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    try:
        assert_execution_review_manifest_current(manifest_id)
        if payload.decision == "authorize_read_only_execution":
            manifest = get_execution_review_manifest(manifest_id, include_payload=True)
            if not manifest:
                raise KeyError("execution_review_manifest_not_found")
            proposed = manifest.get("payload", {}).get("proposed_execution", {}) or {}
            capability_id = str(proposed.get("capability_id") or "")
            readiness = capability_readiness(base)
            target = next(
                (item for item in readiness.get("items", []) if str(item.get("id")) == capability_id),
                None,
            )
            if not target or target.get("healthy") is not True:
                raise ValueError("capability_not_healthy_at_authorization")
        authorization = append_execution_authorization(manifest_id, payload)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-final-execution-authorization.v1",
        "authorization": authorization,
        "lineage_freshness_verified": True,
        "live_capability_health_required_for_authorize": True,
        "execution_authorized": authorization["execution_authorized"],
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": authorization["next_gate"],
    }
