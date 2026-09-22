from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import api.runtime_v31 as previous
import api.runtime_v23 as session_base
import api.runtime_v24 as console_control
from api.execution_review import ExecutionReviewInput, prepare_execution_review_manifest
from api.lineage_guard import assert_action_packet_current
from api.operator_console_execution_review import CONSOLE_HTML_V32
from api.review_ledger import ledger_path

previous.base.VERSION = "0.32.0"
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


def _authorization_action_packet_id(authorization_id: str) -> str:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT action_packet_id FROM authorization_records WHERE authorization_id = ? LIMIT 1",
            (authorization_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise KeyError("authorization_not_found")
    return str(row["action_packet_id"])


@app.get(_CONSOLE_PATH)
def operator_console_page_v32(request: Request) -> Any:
    if not session_base._has_session(request):
        return RedirectResponse("/operator/login", status_code=303)
    return session_base._security_headers(HTMLResponse(CONSOLE_HTML_V32))


@app.post("/operator/api/authorizations/{authorization_id}/execution-review")
def operator_console_prepare_execution_review(
    request: Request,
    authorization_id: str,
    payload: ExecutionReviewInput,
    x_vmi_csrf: str | None = base.Header(default=None),
) -> dict[str, Any]:
    console_control._require_csrf(request, x_vmi_csrf)
    try:
        action_packet_id = _authorization_action_packet_id(authorization_id)
        assert_action_packet_current(action_packet_id)
        manifest = prepare_execution_review_manifest(authorization_id, payload)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return {
        "schema": "vmi.operator-console-execution-review-manifest.v1",
        "manifest": manifest,
        "state": "execution_review_prepared",
        "lineage_freshness_verified": True,
        "approval_recorded": True,
        "execution_permitted": False,
        "dispatch_permitted": False,
        "external_actions_executed": 0,
        "next_gate": manifest["next_gate"],
    }
