from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

VERSION = "0.4.0"
ENV = os.getenv("VMI_ENV", "development")
OPERATOR_KEY = os.getenv("VMI_OPERATOR_KEY", "")
OIE_BASE_URL = os.getenv("VMI_OIE_URL", "http://127.0.0.1:3197").rstrip("/")
BUSINESS_ANALYST_BASE_URL = os.getenv("VMI_BUSINESS_ANALYST_URL", "http://127.0.0.1:3194").rstrip("/")
LINKSTREAM_BASE_URL = os.getenv("VMI_LINKSTREAM_URL", "http://127.0.0.1:3181").rstrip("/")
OPPORTUNITY_EXPLORER_BASE_URL = os.getenv("VMI_OPPORTUNITY_EXPLORER_URL", "http://127.0.0.1:3297").rstrip("/")

app = FastAPI(
    title="VirtualMarketInsight Gateway",
    version=VERSION,
    docs_url="/docs" if ENV != "production" else None,
    redoc_url=None,
)

allowed_origins = [
    "https://virtualmarketinsight.com",
    "https://www.virtualmarketinsight.com",
]
if ENV != "production":
    allowed_origins += ["http://localhost:8000", "http://127.0.0.1:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "x-vmi-operator-key"],
)

SurfaceId = Literal[
    "markets",
    "analyst",
    "opportunities",
    "operational-capital",
    "agents",
]

SURFACES: list[dict[str, Any]] = [
    {
        "id": "markets",
        "label": "Explore Markets",
        "state": "routing-live",
        "purpose": "Market, sector, company, commodity and economic relationship discovery.",
    },
    {
        "id": "analyst",
        "label": "Talk to an Analyst",
        "state": "routing-live",
        "purpose": "Evidence, drivers, risk, exposure and decision-context questions.",
    },
    {
        "id": "opportunities",
        "label": "Explore Opportunities",
        "state": "routing-live",
        "purpose": "Operating projects, demand, acquisitions, public-sector and commercial opportunities.",
    },
    {
        "id": "operational-capital",
        "label": "Deploy Operational Capital",
        "state": "routing-live",
        "purpose": "Requirements, resources, capital, capability gaps and implementation planning.",
    },
    {
        "id": "agents",
        "label": "Agent Marketplace",
        "state": "routing-live",
        "purpose": "Specialized agents, systems, automations and operating capabilities.",
    },
]

ROUTES: dict[str, dict[str, Any]] = {
    "markets": {
        "label": "Explore Markets",
        "keywords": [
            "market", "stock", "stocks", "ticker", "equity", "equities", "sector",
            "industry", "commodity", "commodities", "price", "trend", "supply",
            "demand", "macro", "economy", "economic", "company",
        ],
        "graph_path": ["Market", "Evidence", "Relationship", "Opportunity"],
        "capabilities": [
            {"name": "Market Intelligence", "role": "Map companies, sectors and market relationships."},
            {"name": "Commodity Clarity", "role": "Add supply, demand and commodity context when relevant."},
            {"name": "LinkStream", "role": "Expand evidence and relationship discovery."},
            {"name": "Opportunity Intelligence", "role": "Translate signals into operating opportunity paths."},
        ],
        "next_action": "Build the market relationship map, then expand the strongest signals into evidence and opportunity paths.",
    },
    "analyst": {
        "label": "Talk to an Analyst",
        "keywords": [
            "why", "analyze", "analysis", "financial", "financials", "earnings", "revenue",
            "margin", "risk", "valuation", "portfolio", "exposure", "compare", "evidence",
            "driver", "drivers", "outlook", "thesis", "investment",
        ],
        "graph_path": ["Question", "Evidence", "Drivers", "Risk", "Decision Context"],
        "capabilities": [
            {"name": "Financial Intelligence", "role": "Structure the financial and decision question."},
            {"name": "Evidence Layer", "role": "Separate observed evidence from assumptions and interpretation."},
            {"name": "MoneyDragon", "role": "Add capital and portfolio context where appropriate."},
            {"name": "Opportunity Intelligence", "role": "Connect financial signals to real-economy opportunities."},
        ],
        "next_action": "Create an evidence map around the question, then separate drivers, risks, exposures and opportunity paths.",
    },
    "opportunities": {
        "label": "Explore Opportunities",
        "keywords": [
            "opportunity", "opportunities", "rfp", "contract", "contracts", "procurement",
            "project", "projects", "acquisition", "acquire", "manufacturing", "government",
            "public sector", "real estate", "buyer", "buyers", "customer", "customers",
        ],
        "graph_path": ["Demand", "Opportunity", "Requirements", "Evidence", "Buy Box"],
        "capabilities": [
            {"name": "Opportunity Intelligence Engine", "role": "Score demand, evidence and opportunity structure."},
            {"name": "CCAO", "role": "Map the transaction graph and likely buy box."},
            {"name": "Business Assessment", "role": "Assess organizational fit, constraints and commercial readiness."},
            {"name": "Evidence Layer", "role": "Preserve the verified basis for the opportunity thesis."},
        ],
        "next_action": "Structure the opportunity, verify demand evidence, identify requirements and map the smallest credible participation path.",
    },
    "operational-capital": {
        "label": "Deploy Operational Capital",
        "keywords": [
            "capital", "deploy", "deployment", "fund", "funding", "budget", "resources",
            "equipment", "implementation", "implement", "execute", "execution", "build",
            "operate", "operations", "capacity", "capability", "requirements", "finance",
        ],
        "graph_path": ["Opportunity", "Requirements", "Capabilities", "Capital", "Project", "Execution"],
        "capabilities": [
            {"name": "VMI", "role": "Maintain the opportunity, requirements and capital map."},
            {"name": "Shebavonova", "role": "Decompose approved implementation into bounded execution work."},
            {"name": "Enterprise Systems Factory", "role": "Build or integrate missing operating capability."},
            {"name": "Digital Cross Dock", "role": "Move structured evidence and execution payloads between approved systems."},
        ],
        "next_action": "Map requirements and existing capabilities first; identify gaps before any approved capital or execution action is prepared.",
    },
    "agents": {
        "label": "Agent Marketplace",
        "keywords": [
            "agent", "agents", "automation", "automate", "workflow", "workflows", "system",
            "systems", "software", "tool", "tools", "api", "integration", "integrate",
            "bot", "assistant", "operating system",
        ],
        "graph_path": ["Need", "Capability", "Agent/System", "Test", "Approved Operation"],
        "capabilities": [
            {"name": "Agent Marketplace", "role": "Find specialized intelligence and operating agents."},
            {"name": "Enterprise Systems Factory", "role": "Build or integrate a missing capability when no fit exists."},
            {"name": "HDP BOS / Agents", "role": "Provide specialized operating capability behind the front door."},
            {"name": "Digital Cross Dock", "role": "Support controlled information handoff between approved components."},
        ],
        "next_action": "Match the need to an existing capability first; test or simulate before any approved operating connection is made.",
    },
}

PRIORITY = ["analyst", "markets", "opportunities", "operational-capital", "agents"]

# Public-safe metadata only. Internal addresses and credentials are never returned.
CAPABILITY_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "opportunity-intelligence",
        "label": "Opportunity Intelligence Engine",
        "surfaces": ["markets", "analyst", "opportunities", "operational-capital"],
        "integration_state": "read-adapter-live",
        "authority": "read-only evidence",
    },
    {
        "id": "business-analyst",
        "label": "Business Analyst",
        "surfaces": ["analyst", "opportunities", "operational-capital", "agents"],
        "integration_state": "protected-read-ready",
        "authority": "protected internal read contract",
    },
    {
        "id": "linkstream",
        "label": "LinkStream",
        "surfaces": ["markets", "analyst", "agents"],
        "integration_state": "protected-read-ready",
        "authority": "protected internal read contract",
    },
    {
        "id": "opportunity-explorer",
        "label": "Opportunity Explorer",
        "surfaces": ["opportunities"],
        "integration_state": "health-live-contract-pending",
        "authority": "read-only candidate",
    },
    {
        "id": "shebavonova",
        "label": "Shebavonova",
        "surfaces": ["operational-capital", "agents"],
        "integration_state": "configured-offline",
        "authority": "execution requires approval",
    },
    {
        "id": "commodity-clarity",
        "label": "Commodity Clarity",
        "surfaces": ["markets", "analyst"],
        "integration_state": "configured-offline",
        "authority": "read-only candidate",
    },
    {
        "id": "agent-for-sell",
        "label": "AgentForSell",
        "surfaces": ["agents"],
        "integration_state": "configured-offline",
        "authority": "marketplace candidate",
    },
]

OIE_OPERATIONS: dict[str, dict[str, Any]] = {
    "demand_status": {"path": "/api/demand/status", "limit": False},
    "signals": {"path": "/api/demand/signals", "limit": True},
    "matches": {"path": "/api/demand/matches", "limit": True},
    "acquisition": {"path": "/api/demand/acquisition", "limit": True},
    "international_markets": {"path": "/api/international/markets", "limit": True},
    "capabilities": {"path": "/api/demand/capabilities", "limit": False},
    "opportunities": {"path": "/api/opportunities", "limit": True},
    "partners": {"path": "/api/partners", "limit": True},
    "integration_status": {"path": "/api/integrations/status", "limit": False},
    "ontologies": {"path": "/api/ontologies", "limit": False},
}

SURFACE_EVIDENCE_PLAN: dict[str, list[str]] = {
    "markets": ["demand_status", "signals", "international_markets"],
    "analyst": ["demand_status", "signals", "ontologies"],
    "opportunities": ["demand_status", "matches", "opportunities"],
    "operational-capital": ["demand_status", "capabilities", "opportunities"],
    "agents": ["integration_status", "capabilities"],
}

HEALTH_TARGETS: list[dict[str, str]] = [
    {
        "id": "opportunity-intelligence",
        "label": "Opportunity Intelligence Engine",
        "base": OIE_BASE_URL,
        "path": "/health",
    },
    {
        "id": "business-analyst",
        "label": "Business Analyst",
        "base": BUSINESS_ANALYST_BASE_URL,
        "path": "/health",
    },
    {
        "id": "linkstream",
        "label": "LinkStream",
        "base": LINKSTREAM_BASE_URL,
        "path": "/api/health",
    },
    {
        "id": "opportunity-explorer",
        "label": "Opportunity Explorer",
        "base": OPPORTUNITY_EXPLORER_BASE_URL,
        "path": "/health",
    },
]


class RouteRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    starting_surface: SurfaceId | None = None


class EvidenceRequest(RouteRequest):
    limit: int = Field(default=10, ge=1, le=25)


def _resolve_route(request: RouteRequest) -> dict[str, Any]:
    text = " ".join(request.query.lower().split())
    scores: dict[str, int] = {surface_id: 0 for surface_id in ROUTES}
    matched: dict[str, list[str]] = {surface_id: [] for surface_id in ROUTES}

    for surface_id, route in ROUTES.items():
        for keyword in route["keywords"]:
            if keyword in text:
                scores[surface_id] += 2 if " " in keyword else 1
                matched[surface_id].append(keyword)

    if request.starting_surface:
        scores[request.starting_surface] += 4
        matched[request.starting_surface].append("selected starting point")

    max_score = max(scores.values())
    if max_score == 0:
        selected = "analyst"
    else:
        candidates = [key for key, value in scores.items() if value == max_score]
        if request.starting_surface in candidates:
            selected = request.starting_surface
        else:
            selected = next(key for key in PRIORITY if key in candidates)

    selected_score = scores[selected]
    if selected_score >= 6:
        match_level = "strong"
    elif selected_score >= 3:
        match_level = "focused"
    else:
        match_level = "exploratory"

    route = ROUTES[selected]
    return {
        "request_id": str(uuid4()),
        "resolved_surface": selected,
        "label": route["label"],
        "match_level": match_level,
        "signals": list(dict.fromkeys(matched[selected]))[:8],
        "graph_path": route["graph_path"],
        "capability_plan": [
            {**capability, "state": "candidate"} for capability in route["capabilities"]
        ],
        "next_action": route["next_action"],
        "execution_state": "analysis_and_routing_only",
        "external_actions_executed": 0,
        "authority_notice": (
            "This public gateway can classify, map and prepare next steps. It does not itself move capital, "
            "place trades, send outreach, purchase services or trigger private execution systems."
        ),
    }


def _require_operator_key(provided: str | None) -> None:
    if not OPERATOR_KEY:
        raise HTTPException(status_code=503, detail="Operator evidence access is not configured.")
    if not provided or not secrets.compare_digest(provided, OPERATOR_KEY):
        raise HTTPException(status_code=401, detail="Operator authorization required.")


def _compact(value: Any, depth: int = 0) -> Any:
    if depth >= 5:
        return "[depth-limited]"
    if isinstance(value, dict):
        return {str(k): _compact(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_compact(v, depth + 1) for v in value[:10]]
    if isinstance(value, str) and len(value) > 1200:
        return value[:1200] + "…"
    return value


def _json_get(base: str, path: str, params: dict[str, Any] | None = None, timeout: int = 4) -> dict[str, Any]:
    url = f"{base}{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": f"VMI-Gateway/{VERSION}"})
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read(512_000)
            payload = json.loads(raw.decode("utf-8"))
            return {"ok": True, "status": response.status, "data": payload}
    except HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": "upstream_http_error"}
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def _oie_get(operation: str, limit: int) -> dict[str, Any]:
    spec = OIE_OPERATIONS.get(operation)
    if not spec:
        return {"operation": operation, "ok": False, "error": "operation_not_allowed"}

    params: dict[str, Any] = {}
    if spec["limit"]:
        params["limit"] = min(max(limit, 1), 25)

    result = _json_get(OIE_BASE_URL, spec["path"], params=params)
    if result.get("ok"):
        return {
            "operation": operation,
            "ok": True,
            "status": result.get("status"),
            "data": _compact(result.get("data")),
        }
    return {"operation": operation, **result}


def _capability_health() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    safety_fields = [
        "external_writes_enabled",
        "integration_execution_enabled",
        "externalFetchEnabled",
        "externalDispatchEnabled",
        "operating_mode",
        "role",
    ]
    for target in HEALTH_TARGETS:
        result = _json_get(target["base"], target["path"], timeout=3)
        if result.get("ok"):
            data = result.get("data") or {}
            safety = {key: data[key] for key in safety_fields if key in data}
            items.append(
                {
                    "id": target["id"],
                    "label": target["label"],
                    "reachable": True,
                    "status": result.get("status"),
                    "service": data.get("service") or data.get("name") or target["label"],
                    "version": data.get("version"),
                    "safety": safety,
                }
            )
        else:
            items.append(
                {
                    "id": target["id"],
                    "label": target["label"],
                    "reachable": False,
                    "status": result.get("status"),
                    "error": result.get("error", "unreachable"),
                }
            )
    return items


def _operator_evidence(request: EvidenceRequest) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    route = _resolve_route(request)
    operations = SURFACE_EVIDENCE_PLAN[route["resolved_surface"]]
    evidence = [_oie_get(operation, request.limit) for operation in operations]
    return route, evidence


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "virtualmarketinsight-gateway",
        "version": VERSION,
        "routing": "live",
        "evidence_adapters": "gated",
        "capability_health": "gated",
        "execution": "gated",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "virtualmarketinsight-gateway",
        "version": VERSION,
        "environment": ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/surfaces")
def surfaces() -> dict[str, Any]:
    return {"items": SURFACES, "count": len(SURFACES)}


@app.get("/api/v1/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "items": CAPABILITY_REGISTRY,
        "count": len(CAPABILITY_REGISTRY),
        "internal_addresses_exposed": False,
        "execution": "gated",
    }


@app.get("/api/v1/router/capabilities")
def router_capabilities() -> dict[str, Any]:
    return {
        "routing": "live",
        "execution": "gated",
        "items": [
            {
                "id": surface_id,
                "label": route["label"],
                "graph_path": route["graph_path"],
                "capabilities": [capability["name"] for capability in route["capabilities"]],
            }
            for surface_id, route in ROUTES.items()
        ],
    }


@app.post("/api/v1/router/resolve")
def resolve_router(request: RouteRequest) -> dict[str, Any]:
    return _resolve_route(request)


@app.get("/api/v1/operator/capabilities/health")
def operator_capability_health(
    x_vmi_operator_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    items = _capability_health()
    return {
        "items": items,
        "reachable_count": sum(1 for item in items if item["reachable"]),
        "count": len(items),
        "external_actions_executed": 0,
        "execution_state": "health_read_only",
    }


@app.post("/api/v1/operator/evidence/preview")
def operator_evidence_preview(
    request: EvidenceRequest,
    x_vmi_operator_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    route, evidence = _operator_evidence(request)
    return {
        "request_id": route["request_id"],
        "resolved_surface": route["resolved_surface"],
        "graph_path": route["graph_path"],
        "adapter": "opportunity-intelligence",
        "adapter_authority": "read-only",
        "evidence": evidence,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "external_actions_executed": 0,
        "execution_state": "evidence_gathering_only",
    }


@app.post("/api/v1/operator/brief")
def operator_brief(
    request: EvidenceRequest,
    x_vmi_operator_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    route, evidence = _operator_evidence(request)
    return {
        "request_id": route["request_id"],
        "route": route,
        "capability_health": _capability_health(),
        "evidence": {
            "adapter": "opportunity-intelligence",
            "authority": "read-only",
            "items": evidence,
        },
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "external_actions_executed": 0,
        "execution_state": "operator_brief_only",
        "next_gate": "Human review before any external or execution action.",
    }


@app.get("/api/v1/graph/sample")
def sample_graph() -> dict[str, Any]:
    return {
        "illustrative": True,
        "nodes": [
            {"id": "opportunity", "type": "Opportunity"},
            {"id": "requirements", "type": "Requirement"},
            {"id": "capabilities", "type": "Capability"},
            {"id": "capital", "type": "CapitalMandate"},
            {"id": "project", "type": "Project"},
            {"id": "execution", "type": "Execution"},
        ],
        "edges": [
            ["opportunity", "requirements"],
            ["requirements", "capabilities"],
            ["capabilities", "capital"],
            ["capital", "project"],
            ["project", "execution"],
        ],
    }
