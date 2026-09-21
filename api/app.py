from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

VERSION = "0.1.0"
ENV = os.getenv("VMI_ENV", "development")
app = FastAPI(title="VirtualMarketInsight Gateway", version=VERSION, docs_url="/docs" if ENV != "production" else None, redoc_url=None)
allowed_origins = ["https://virtualmarketinsight.com", "https://www.virtualmarketinsight.com"]
if ENV != "production": allowed_origins += ["http://localhost:8000", "http://127.0.0.1:8000"]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])
SURFACES = [
 {"id":"markets","label":"Explore Markets","state":"planned"},
 {"id":"analyst","label":"Talk to an Analyst","state":"planned"},
 {"id":"opportunities","label":"Explore Opportunities","state":"planned"},
 {"id":"operational-capital","label":"Deploy Operational Capital","state":"planned"},
 {"id":"agents","label":"Agent Marketplace","state":"planned"},
]
@app.get("/health")
def health() -> dict[str, Any]: return {"ok":True,"service":"virtualmarketinsight-gateway","version":VERSION,"environment":ENV,"timestamp":datetime.now(timezone.utc).isoformat()}
@app.get("/api/v1/surfaces")
def surfaces() -> dict[str, Any]: return {"items":SURFACES,"count":len(SURFACES)}
@app.get("/api/v1/graph/sample")
def sample_graph() -> dict[str, Any]:
 return {"illustrative":True,"nodes":[{"id":"opportunity","type":"Opportunity"},{"id":"requirements","type":"Requirement"},{"id":"capabilities","type":"Capability"},{"id":"capital","type":"CapitalMandate"},{"id":"project","type":"Project"},{"id":"execution","type":"Execution"}],"edges":[["opportunity","requirements"],["requirements","capabilities"],["capabilities","capital"],["capital","project"],["project","execution"]]}
