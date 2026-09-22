from __future__ import annotations

from typing import Any

import api.runtime_v26 as previous

previous.base.VERSION = "0.27.0"
app = previous.app
base = previous.base


@app.get("/api/v1/operator/lineage-guard/action-packets/schema")
def operator_action_packet_freshness_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.lineage-freshness-guard.v3",
        "review_record_must_be_current": True,
        "review_event_must_be_latest_for_record": True,
        "bounded_action_packet_must_be_latest_for_event": True,
        "superseded_action_packet_reuse_permitted": False,
        "historical_artifacts_remain_readable": True,
        "external_actions_executed": 0,
    }
