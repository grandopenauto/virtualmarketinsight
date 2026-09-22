from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

VERSION = "0.2.0"
ENV = os.getenv("VMI_ENV", "development")

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
    allow_headers=["content-type"],
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


class RouteRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    starting_surface: SurfaceId | None = None


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


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "virtualmarketinsight-gateway",
        "version": VERSION,
        "routing": "live",
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
