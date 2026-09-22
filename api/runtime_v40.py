from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import api.runtime_v39 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.evidence_return import prepare_evidence_return
from api.evidence_return_context import build_evidence_return_context
from api.operator_console_evidence_return import CONSOLE_HTML_V40

previous.base.VERSION = "0.40.0"
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


class EvidenceReturnConfirmation(BaseModel):
    confirm_return_evidence: bool = False


@app.get(_CONSOLE_PATH)
def operator_console_page_v40(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V40))


@app.get("/operator/api/cases/{record_id}/evidence-return-context")
def operator_console_evidence_return_context(request: Request, record_id: str) -> dict[str, Any]:
    session_base._require_session(request)
    try:
        return build_evidence_return_context(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))


@app.post("/operator/api/read-only-executions/{execution_receipt_id}/evidence-return")
def operator_console_return_evidence(
    request: Request,
    execution_receipt_id: str,
    payload: EvidenceReturnConfirmation,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    if payload.confirm_return_evidence is not True:
        raise base.HTTPException(status_code=409, detail="Explicit evidence-return confirmation required.")
    try:
        packet = prepare_evidence_return(execution_receipt_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-evidence-return.v1",
        "evidence_return": packet,
        "decision_refresh_created": False,
        "successor_review_created": False,
        "approval_recorded": False,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": packet["next_gate"],
    }
