from __future__ import annotations

from typing import Any

import api.runtime_v18 as previous
from api.decision_dossiers import build_decision_dossier

previous.base.VERSION = "0.19.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/decision-dossiers/schema")
def operator_decision_dossiers_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.decision-dossier.v1",
        "purpose": "Reconstruct a complete multi-generation decision lineage across governed review and read-only execution artifacts without exposing raw evidence bodies by default.",
        "metadata_first": True,
        "cross_cycle": True,
        "chain_integrity_checks": True,
        "view_only": True,
        "approval_authority": False,
        "execution_authority": False,
        "dispatch_authority": False,
        "external_actions_executed": 0,
    }


@app.get("/api/v1/operator/decision-dossiers/{record_id}")
def operator_decision_dossier_get(
    record_id: str,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    try:
        dossier = build_decision_dossier(record_id)
    except KeyError as exc:
        raise base.HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise base.HTTPException(status_code=409, detail=str(exc))
    return dossier
