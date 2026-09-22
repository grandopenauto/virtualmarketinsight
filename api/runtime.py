from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import api.app as base

# Runtime augmentation of the proven v0.4 gateway. Keeping this layer small makes
# the Business Analyst adapter independently reversible while its contract matures.
base.VERSION = "0.5.0"
app = base.app

BA_READ_KEY = os.getenv("VMI_BA_READ_KEY", "")
BA_BASE_URL = os.getenv("VMI_BUSINESS_ANALYST_URL", "http://127.0.0.1:3194").rstrip("/")

# VMI callers never supply an arbitrary Business Analyst path. These exact named
# surfaces are already allow-listed by Business Analyst's native adapter layer.
BA_READ_PLAN: dict[str, list[tuple[str, str]]] = {
    "markets": [
        ("seoagent", "operations"),
        ("entrepreneuragent", "core_overview"),
    ],
    "analyst": [
        ("accountingagent", "entities"),
        ("entrepreneuragent", "core_overview"),
    ],
    "opportunities": [
        ("leadwizard", "contractors"),
        ("leadwizard", "company_profiles"),
        ("entrepreneuragent", "core_overview"),
    ],
    "operational-capital": [
        ("accountingagent", "entities"),
        ("webdevagent", "orchestration"),
        ("entrepreneuragent", "core_overview"),
    ],
    "agents": [
        ("entrepreneuragent", "agents"),
        ("webdevagent", "studio"),
        ("leadwizard", "connector_manifest"),
    ],
}

# Promote the registry only in this runtime. No internal URL or credential is
# included in the public metadata.
for item in base.CAPABILITY_REGISTRY:
    if item.get("id") == "business-analyst":
        item["integration_state"] = "read-adapter-live"
        item["authority"] = "dedicated read-only native adapter"


def _ba_read(agent_id: str, surface: str) -> dict[str, Any]:
    allowed = {(agent, name) for pairs in BA_READ_PLAN.values() for agent, name in pairs}
    if (agent_id, surface) not in allowed:
        return {
            "agent_id": agent_id,
            "surface": surface,
            "ok": False,
            "error": "surface_not_allowed",
        }
    if not BA_READ_KEY:
        return {
            "agent_id": agent_id,
            "surface": surface,
            "ok": False,
            "error": "adapter_not_configured",
        }

    path = (
        "/api/business-analyst/native/"
        + quote(agent_id, safe="")
        + "/read/"
        + quote(surface, safe="")
    )
    req = Request(
        BA_BASE_URL + path,
        headers={
            "Accept": "application/json",
            "User-Agent": f"VMI-Gateway/{base.VERSION}",
            "x-vmi-read-key": BA_READ_KEY,
        },
    )
    try:
        with urlopen(req, timeout=5) as response:
            raw = response.read(512_000)
            payload = json.loads(raw.decode("utf-8"))
            return {
                "agent_id": agent_id,
                "surface": surface,
                "ok": bool(payload.get("success", response.status == 200)),
                "status": response.status,
                "adapter_status": payload.get("status"),
                "data": base._compact(payload),
            }
    except HTTPError as exc:
        return {
            "agent_id": agent_id,
            "surface": surface,
            "ok": False,
            "status": exc.code,
            "error": "upstream_http_error",
        }
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "agent_id": agent_id,
            "surface": surface,
            "ok": False,
            "error": type(exc).__name__,
        }


def _ba_reads_for_surface(surface: str) -> list[dict[str, Any]]:
    return [_ba_read(agent, name) for agent, name in BA_READ_PLAN.get(surface, [])]


# Replace the v0.4 operator brief while leaving every other route unchanged.
app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/api/v1/operator/brief"
        and "POST" in getattr(route, "methods", set())
    )
]


@app.post("/api/v1/operator/brief")
def operator_brief_v05(
    request: base.EvidenceRequest,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    route, oie_evidence = base._operator_evidence(request)
    native_reads = _ba_reads_for_surface(route["resolved_surface"])

    return {
        "request_id": route["request_id"],
        "route": route,
        "capability_health": base._capability_health(),
        "evidence": {
            "opportunity_intelligence": {
                "authority": "read-only",
                "items": oie_evidence,
            },
            "business_analyst_native": {
                "authority": "dedicated read-only native adapter",
                "configured": bool(BA_READ_KEY),
                "items": native_reads,
            },
        },
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "external_actions_executed": 0,
        "execution_state": "operator_brief_only",
        "next_gate": "Human review before any external, analysis-generation, or execution action.",
    }


@app.get("/api/v1/operator/native/read-plan")
def operator_native_read_plan(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "adapter": "business-analyst-native",
        "configured": bool(BA_READ_KEY),
        "authority": "read-only",
        "surfaces": {
            surface: [
                {"agent_id": agent_id, "surface": read_surface}
                for agent_id, read_surface in pairs
            ]
            for surface, pairs in BA_READ_PLAN.items()
        },
        "arbitrary_paths_allowed": False,
        "analysis_allowed": False,
        "execution_allowed": False,
    }
