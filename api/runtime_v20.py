from __future__ import annotations

from typing import Any

import api.runtime_v19 as previous
from api.governance_monitor import evaluate_governance

previous.base.VERSION = "0.20.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/governance-monitor/schema")
def operator_governance_monitor_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.governance-monitor.v1",
        "purpose": "Evaluate a decision dossier for chain integrity, stale authority, expired or unconsumed dispatch artifacts, incomplete evidence return cycles, unresolved gaps, and the current human gate.",
        "monitor_only": True,
        "automatic_advancement_permitted": False,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/governance-monitor/{record_id}")
def operator_governance_monitor_get(
    record_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        return evaluate_governance(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
