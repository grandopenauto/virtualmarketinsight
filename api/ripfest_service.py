from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from ripfest import router as ripfest_router
except ImportError:  # package execution
    from .ripfest import router as ripfest_router

VERSION = "0.1.0"
ENV = os.getenv("VMI_ENV", "development")

app = FastAPI(
    title="VMI Collectibles Market Intelligence",
    description="Project RipFest private buy-box, asset matching, quote and market-memory service.",
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

app.include_router(ripfest_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "vmi-collectibles-market-intelligence",
        "codename": "project-ripfest",
        "version": VERSION,
        "network": "private-first",
        "external_execution": "gated",
    }


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "service": "vmi-collectibles-market-intelligence",
        "version": VERSION,
        "environment": ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
