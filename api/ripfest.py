from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["Project RipFest / VMI Collectibles"])

DB_PATH = Path(
    os.getenv(
        "VMI_COLLECTIBLES_DB",
        str(Path(__file__).resolve().parent.parent / "data" / "vmi_collectibles.db"),
    )
)
OPERATOR_KEY = os.getenv("VMI_OPERATOR_KEY", "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_operator_key(provided: str | None) -> None:
    if not OPERATOR_KEY:
        raise HTTPException(status_code=503, detail="VMI operator access is not configured.")
    if not provided or not secrets.compare_digest(provided, OPERATOR_KEY):
        raise HTTPException(status_code=401, detail="Operator authorization required.")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dealers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                website TEXT,
                contact_name TEXT,
                email TEXT,
                phone TEXT,
                location TEXT,
                status TEXT NOT NULL DEFAULT 'prospect',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS buy_boxes (
                id TEXT PRIMARY KEY,
                dealer_id TEXT NOT NULL,
                category TEXT NOT NULL,
                game TEXT,
                product_type TEXT,
                year_min INTEGER,
                year_max INTEGER,
                grading_company TEXT,
                min_grade REAL,
                target_pct_comp REAL,
                max_unit_price REAL,
                max_monthly_volume REAL,
                keywords_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (dealer_id) REFERENCES dealers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                game TEXT,
                year INTEGER,
                product_type TEXT,
                grading_company TEXT,
                grade REAL,
                estimated_market_value REAL,
                ask_price REAL,
                source TEXT,
                source_ref TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quotes (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                dealer_id TEXT NOT NULL,
                amount REAL NOT NULL,
                quote_type TEXT NOT NULL DEFAULT 'cash',
                status TEXT NOT NULL DEFAULT 'open',
                expires_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
                FOREIGN KEY (dealer_id) REFERENCES dealers(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_buy_boxes_dealer ON buy_boxes(dealer_id);
            CREATE INDEX IF NOT EXISTS idx_buy_boxes_category ON buy_boxes(category, game, active);
            CREATE INDEX IF NOT EXISTS idx_assets_category ON assets(category, game, year);
            CREATE INDEX IF NOT EXISTS idx_quotes_asset ON quotes(asset_id, status);
            """
        )


_init_db()


class DealerIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    contact_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=240)
    status: Literal["prospect", "contacted", "qualified", "active", "paused"] = "prospect"
    notes: str | None = Field(default=None, max_length=4000)


class BuyBoxIn(BaseModel):
    dealer_id: str
    category: str = Field(min_length=2, max_length=100)
    game: str | None = Field(default=None, max_length=120)
    product_type: str | None = Field(default=None, max_length=120)
    year_min: int | None = Field(default=None, ge=1800, le=2200)
    year_max: int | None = Field(default=None, ge=1800, le=2200)
    grading_company: str | None = Field(default=None, max_length=80)
    min_grade: float | None = Field(default=None, ge=0, le=10)
    target_pct_comp: float | None = Field(default=None, gt=0, le=200)
    max_unit_price: float | None = Field(default=None, ge=0)
    max_monthly_volume: float | None = Field(default=None, ge=0)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    active: bool = True


class AssetIn(BaseModel):
    title: str = Field(min_length=2, max_length=400)
    category: str = Field(min_length=2, max_length=100)
    game: str | None = Field(default=None, max_length=120)
    year: int | None = Field(default=None, ge=1800, le=2200)
    product_type: str | None = Field(default=None, max_length=120)
    grading_company: str | None = Field(default=None, max_length=80)
    grade: float | None = Field(default=None, ge=0, le=10)
    estimated_market_value: float | None = Field(default=None, ge=0)
    ask_price: float | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=120)
    source_ref: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuoteIn(BaseModel):
    asset_id: str
    dealer_id: str
    amount: float = Field(gt=0)
    quote_type: Literal["cash", "store_credit", "consignment", "conditional"] = "cash"
    status: Literal["open", "accepted", "declined", "expired", "withdrawn"] = "open"
    expires_at: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class MatchRequest(BaseModel):
    asset_id: str
    max_results: int = Field(default=25, ge=1, le=100)


def _dealer_exists(conn: sqlite3.Connection, dealer_id: str) -> bool:
    return conn.execute("SELECT 1 FROM dealers WHERE id = ?", (dealer_id,)).fetchone() is not None


def _asset_exists(conn: sqlite3.Connection, asset_id: str) -> bool:
    return conn.execute("SELECT 1 FROM assets WHERE id = ?", (asset_id,)).fetchone() is not None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _box_matches_asset(box: sqlite3.Row, asset: sqlite3.Row) -> tuple[bool, list[str], float]:
    reasons: list[str] = []
    score = 0.0

    if _norm(box["category"]) != _norm(asset["category"]):
        return False, [], 0.0
    score += 40
    reasons.append("category")

    if box["game"]:
        if _norm(box["game"]) != _norm(asset["game"]):
            return False, [], 0.0
        score += 15
        reasons.append("game")

    if box["product_type"]:
        if _norm(box["product_type"]) != _norm(asset["product_type"]):
            return False, [], 0.0
        score += 10
        reasons.append("product_type")

    if box["year_min"] is not None:
        if asset["year"] is None or asset["year"] < box["year_min"]:
            return False, [], 0.0
        score += 5
        reasons.append("year_min")

    if box["year_max"] is not None:
        if asset["year"] is None or asset["year"] > box["year_max"]:
            return False, [], 0.0
        score += 5
        reasons.append("year_max")

    if box["grading_company"]:
        if _norm(box["grading_company"]) != _norm(asset["grading_company"]):
            return False, [], 0.0
        score += 10
        reasons.append("grading_company")

    if box["min_grade"] is not None:
        if asset["grade"] is None or asset["grade"] < box["min_grade"]:
            return False, [], 0.0
        score += 5
        reasons.append("min_grade")

    keywords = json.loads(box["keywords_json"] or "[]")
    if keywords:
        title = _norm(asset["title"])
        hits = [keyword for keyword in keywords if _norm(keyword) in title]
        if not hits:
            return False, [], 0.0
        score += min(10, len(hits) * 3)
        reasons.append("keywords")

    return True, reasons, min(score, 100.0)


def _indicated_max(box: sqlite3.Row, asset: sqlite3.Row) -> float | None:
    candidates: list[float] = []
    comp = asset["estimated_market_value"]
    if comp is not None and box["target_pct_comp"] is not None:
        candidates.append(float(comp) * float(box["target_pct_comp"]) / 100.0)
    if box["max_unit_price"] is not None:
        candidates.append(float(box["max_unit_price"]))
    if not candidates:
        return None
    return min(candidates)


@router.get("/api/v1/collectibles/status")
def public_status() -> dict[str, Any]:
    return {
        "module": "VMI Collectibles Market Intelligence",
        "codename": "Project RipFest",
        "state": "private-network-foundation",
        "public_trading": False,
        "external_market_dependency": False,
        "execution": "operator-gated",
        "core_graph": [
            "Dealer/Collector",
            "Buy Box",
            "Asset",
            "Market Evidence",
            "Match",
            "Executable Quote",
            "Transaction",
            "Commercial Memory",
        ],
    }


@router.get("/api/v1/operator/collectibles/summary")
def summary(x_vmi_operator_key: str | None = Header(default=None)) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    with _connect() as conn:
        counts = {
            "dealers": conn.execute("SELECT COUNT(*) FROM dealers").fetchone()[0],
            "active_buy_boxes": conn.execute("SELECT COUNT(*) FROM buy_boxes WHERE active = 1").fetchone()[0],
            "assets": conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
            "open_quotes": conn.execute("SELECT COUNT(*) FROM quotes WHERE status = 'open'").fetchone()[0],
        }
    return {"module": "project-ripfest", "counts": counts, "database": "private", "timestamp": _now()}


@router.post("/api/v1/operator/collectibles/dealers")
def create_dealer(payload: DealerIn, x_vmi_operator_key: str | None = Header(default=None)) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    dealer_id = str(uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dealers
            (id, name, website, contact_name, email, phone, location, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dealer_id, payload.name, payload.website, payload.contact_name, payload.email, payload.phone,
             payload.location, payload.status, payload.notes, now, now),
        )
    return {"id": dealer_id, "created": True}


@router.get("/api/v1/operator/collectibles/dealers")
def list_dealers(
    limit: int = Query(default=100, ge=1, le=500),
    x_vmi_operator_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, website, location, status, created_at, updated_at FROM dealers ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "count": len(rows)}


@router.post("/api/v1/operator/collectibles/buy-boxes")
def create_buy_box(payload: BuyBoxIn, x_vmi_operator_key: str | None = Header(default=None)) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    buy_box_id = str(uuid4())
    now = _now()
    with _connect() as conn:
        if not _dealer_exists(conn, payload.dealer_id):
            raise HTTPException(status_code=404, detail="Dealer not found.")
        conn.execute(
            """INSERT INTO buy_boxes
            (id, dealer_id, category, game, product_type, year_min, year_max, grading_company, min_grade,
             target_pct_comp, max_unit_price, max_monthly_volume, keywords_json, notes, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (buy_box_id, payload.dealer_id, payload.category, payload.game, payload.product_type,
             payload.year_min, payload.year_max, payload.grading_company, payload.min_grade,
             payload.target_pct_comp, payload.max_unit_price, payload.max_monthly_volume,
             json.dumps(payload.keywords), payload.notes, 1 if payload.active else 0, now, now),
        )
    return {"id": buy_box_id, "created": True}


@router.get("/api/v1/operator/collectibles/buy-boxes")
def list_buy_boxes(
    limit: int = Query(default=100, ge=1, le=500),
    x_vmi_operator_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT b.*, d.name AS dealer_name
            FROM buy_boxes b JOIN dealers d ON d.id = b.dealer_id
            ORDER BY b.updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["keywords"] = json.loads(item.pop("keywords_json") or "[]")
        item["active"] = bool(item["active"])
        items.append(item)
    return {"items": items, "count": len(items)}


@router.post("/api/v1/operator/collectibles/assets")
def create_asset(payload: AssetIn, x_vmi_operator_key: str | None = Header(default=None)) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    asset_id = str(uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO assets
            (id, title, category, game, year, product_type, grading_company, grade, estimated_market_value,
             ask_price, source, source_ref, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (asset_id, payload.title, payload.category, payload.game, payload.year, payload.product_type,
             payload.grading_company, payload.grade, payload.estimated_market_value, payload.ask_price,
             payload.source, payload.source_ref, json.dumps(payload.metadata), now, now),
        )
    return {"id": asset_id, "created": True}


@router.get("/api/v1/operator/collectibles/assets")
def list_assets(
    limit: int = Query(default=100, ge=1, le=500),
    x_vmi_operator_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM assets ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        items.append(item)
    return {"items": items, "count": len(items)}


@router.post("/api/v1/operator/collectibles/quotes")
def create_quote(payload: QuoteIn, x_vmi_operator_key: str | None = Header(default=None)) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    quote_id = str(uuid4())
    with _connect() as conn:
        if not _dealer_exists(conn, payload.dealer_id):
            raise HTTPException(status_code=404, detail="Dealer not found.")
        if not _asset_exists(conn, payload.asset_id):
            raise HTTPException(status_code=404, detail="Asset not found.")
        conn.execute(
            """INSERT INTO quotes
            (id, asset_id, dealer_id, amount, quote_type, status, expires_at, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (quote_id, payload.asset_id, payload.dealer_id, payload.amount, payload.quote_type,
             payload.status, payload.expires_at, payload.notes, _now()),
        )
    return {"id": quote_id, "created": True}


@router.post("/api/v1/operator/collectibles/match")
def match_asset(payload: MatchRequest, x_vmi_operator_key: str | None = Header(default=None)) -> dict[str, Any]:
    _require_operator_key(x_vmi_operator_key)
    with _connect() as conn:
        asset = conn.execute("SELECT * FROM assets WHERE id = ?", (payload.asset_id,)).fetchone()
        if asset is None:
            raise HTTPException(status_code=404, detail="Asset not found.")
        boxes = conn.execute(
            """SELECT b.*, d.name AS dealer_name, d.status AS dealer_status
            FROM buy_boxes b JOIN dealers d ON d.id = b.dealer_id
            WHERE b.active = 1 AND d.status IN ('qualified', 'active', 'contacted')"""
        ).fetchall()
        open_quotes = conn.execute(
            """SELECT q.*, d.name AS dealer_name FROM quotes q JOIN dealers d ON d.id = q.dealer_id
            WHERE q.asset_id = ? AND q.status = 'open' ORDER BY q.amount DESC""",
            (payload.asset_id,),
        ).fetchall()

    matches: list[dict[str, Any]] = []
    ask_price = asset["ask_price"]
    for box in boxes:
        matched, reasons, score = _box_matches_asset(box, asset)
        if not matched:
            continue
        indicated = _indicated_max(box, asset)
        spread = None
        executable_from_box = None
        if indicated is not None and ask_price is not None:
            spread = indicated - float(ask_price)
            executable_from_box = spread >= 0
            score += 10 if executable_from_box else 0
        matches.append(
            {
                "buy_box_id": box["id"],
                "dealer_id": box["dealer_id"],
                "dealer_name": box["dealer_name"],
                "dealer_status": box["dealer_status"],
                "match_score": min(round(score, 2), 100.0),
                "matched_on": reasons,
                "indicated_max_price": round(indicated, 2) if indicated is not None else None,
                "ask_price": ask_price,
                "indicated_spread": round(spread, 2) if spread is not None else None,
                "box_can_clear_ask": executable_from_box,
            }
        )

    matches.sort(
        key=lambda item: (
            item["box_can_clear_ask"] is True,
            item["indicated_max_price"] if item["indicated_max_price"] is not None else -1,
            item["match_score"],
        ),
        reverse=True,
    )
    matches = matches[: payload.max_results]

    quotes = [dict(row) for row in open_quotes]
    best_quote = max((row["amount"] for row in quotes), default=None)
    indicated_prices = [m["indicated_max_price"] for m in matches if m["indicated_max_price"] is not None]
    best_indicated = max(indicated_prices, default=None)
    executable_quote = best_quote is not None and ask_price is not None and best_quote >= ask_price
    executable_box = any(m["box_can_clear_ask"] is True for m in matches)

    if executable_quote:
        readiness = "executable_quote"
    elif executable_box:
        readiness = "buy_box_can_clear_ask"
    elif matches:
        readiness = "matched_demand"
    else:
        readiness = "no_known_buyer"

    return {
        "asset": {
            "id": asset["id"],
            "title": asset["title"],
            "estimated_market_value": asset["estimated_market_value"],
            "ask_price": ask_price,
        },
        "readiness": readiness,
        "dealer_depth": len({m["dealer_id"] for m in matches}),
        "buy_box_matches": matches,
        "open_quotes": quotes,
        "best_open_quote": best_quote,
        "best_indicated_buy_box_price": best_indicated,
        "external_actions_executed": 0,
        "next_action": (
            "Route the asset to matched buyers for explicit quotes."
            if readiness in {"matched_demand", "buy_box_can_clear_ask"}
            else "No automated transaction has been executed."
        ),
    }
