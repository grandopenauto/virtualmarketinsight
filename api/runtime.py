from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import api.app as base
from api.decision_packet import build_decision_packet

# Runtime augmentation of the proven gateway. Keeping this layer small makes
# read adapters and decision packets independently reversible as contracts mature.
base.VERSION = "0.6.0"
app = base.app

BA_READ_PROXY_URL = os.getenv(
    "VMI_BA_READ_PROXY_URL", "http://127.0.0.1:3193"
).rstrip("/")

# VMI callers never supply an arbitrary Business Analyst path. These exact named
# surfaces are already allow-listed by the loopback sidecar and Business Analyst's
# native adapter layer.
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

for item in base.CAPABILITY_REGISTRY:
    if item.get("id") == "business-analyst":
        item["integration_state"] = "read-adapter-live"
        item["authority"] = "loopback-only read adapter"

if not any(item.get("id") == "business-analyst-vmi-read" for item in base.HEALTH_TARGETS):
    base.HEALTH_TARGETS.append(
        {
            "id": "business-analyst-vmi-read",
            "label": "Business Analyst VMI Read Sidecar",
            "base": BA_READ_PROXY_URL,
            "path": "/health",
        }
    )


def _sidecar_health() -> dict[str, Any]:
    req = Request(
        BA_READ_PROXY_URL + "/health",
        headers={"Accept": "application/json", "User-Agent": f"VMI-Gateway/{base.VERSION}"},
    )
    try:
        with urlopen(req, timeout=3) as response:
            payload = json.loads(response.read(128_000).decode("utf-8"))
            return {"ok": bool(payload.get("ok")), "status": response.status, "data": payload}
    except HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": "upstream_http_error"}
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def _ba_read(agent_id: str, surface: str) -> dict[str, Any]:
    allowed = {(agent, name) for pairs in BA_READ_PLAN.values() for agent, name in pairs}
    if (agent_id, surface) not in allowed:
        return {
            "agent_id": agent_id,
            "surface": surface,
            "ok": False,
            "error": "surface_not_allowed",
        }

    path = "/read/" + quote(agent_id, safe="") + "/" + quote(surface, safe="")
    req = Request(
        BA_READ_PROXY_URL + path,
        headers={"Accept": "application/json", "User-Agent": f"VMI-Gateway/{base.VERSION}"},
    )
    try:
        with urlopen(req, timeout=6) as response:
            raw = response.read(512_000)
            payload = json.loads(raw.decode("utf-8"))
            return {
                "agent_id": agent_id,
                "surface": surface,
                "ok": bool(payload.get("success", payload.get("ok", response.status == 200))),
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


def _build_operator_brief(request: base.EvidenceRequest) -> dict[str, Any]:
    """Build the operator packet after authorization has already been decided."""
    route, oie_evidence = base._operator_evidence(request)
    native_reads = _ba_reads_for_surface(route["resolved_surface"])
    sidecar = _sidecar_health()

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
                "authority": "loopback-only read adapter",
                "configured": bool(sidecar.get("ok")),
                "items": native_reads,
            },
        },
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "external_actions_executed": 0,
        "execution_state": "operator_brief_only",
        "next_gate": "Human review before any external, analysis-generation, or execution action.",
    }


def _build_decision_packet(request: base.EvidenceRequest) -> dict[str, Any]:
    brief = _build_operator_brief(request)
    return build_decision_packet(request, brief)


# Replace the base operator brief while leaving every other route unchanged.
app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/api/v1/operator/brief"
        and "POST" in getattr(route, "methods", set())
    )
]


@app.post("/api/v1/operator/brief")
def operator_brief_v06(
    request: base.EvidenceRequest,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return _build_operator_brief(request)


@app.post("/api/v1/operator/decision-packet")
def operator_decision_packet_v1(
    request: base.EvidenceRequest,
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return _build_decision_packet(request)


@app.get("/api/v1/operator/decision-packet/schema")
def operator_decision_packet_schema(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    return {
        "schema": "vmi.decision-packet.v1",
        "purpose": "Package routed intent, evidence, capability readiness, gaps and approval gates for human review.",
        "external_execution_permitted": False,
        "external_actions_executed": 0,
        "required_sections": [
            "intent",
            "execution_graph",
            "capability_plan",
            "capability_health",
            "evidence",
            "evidence_summary",
            "gaps",
            "authority",
            "approval_gates",
            "review_options",
            "next_gate",
        ],
    }


@app.get("/api/v1/operator/native/read-plan")
def operator_native_read_plan(
    x_vmi_operator_key: str | None = base.Header(default=None),
) -> dict[str, Any]:
    base._require_operator_key(x_vmi_operator_key)
    sidecar = _sidecar_health()
    return {
        "adapter": "business-analyst-native",
        "configured": bool(sidecar.get("ok")),
        "transport": "loopback-only sidecar",
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
