from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _probe(target: dict[str, str], user_agent: str) -> dict[str, Any]:
    started = time.monotonic()
    req = Request(
        target["base"].rstrip("/") + target["path"],
        headers={"Accept": "application/json", "User-Agent": user_agent},
    )
    try:
        with urlopen(req, timeout=3) as response:
            raw = response.read(96_000)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            ok = bool(payload.get("ok")) or str(payload.get("status", "")).lower() in {
                "ok", "healthy", "ready", "running"
            }
            return {
                "id": target["id"],
                "label": target["label"],
                "reachable": True,
                "healthy": ok,
                "http_status": response.status,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "reported_status": payload.get("status"),
            }
    except HTTPError as exc:
        return {
            "id": target["id"],
            "label": target["label"],
            "reachable": True,
            "healthy": False,
            "http_status": exc.code,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "error": "upstream_http_error",
        }
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "id": target["id"],
            "label": target["label"],
            "reachable": False,
            "healthy": False,
            "http_status": None,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "error": type(exc).__name__,
        }


def capability_readiness(base_module: Any) -> dict[str, Any]:
    registry = {str(item["id"]): dict(item) for item in base_module.CAPABILITY_REGISTRY}
    targets = list(base_module.HEALTH_TARGETS)
    health: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, min(len(targets), 8))) as pool:
        futures = {
            pool.submit(_probe, target, f"VMI-OperatorConsole/{base_module.VERSION}"): target["id"]
            for target in targets
        }
        for future in as_completed(futures):
            result = future.result()
            health[str(result["id"])] = result

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for capability_id, meta in registry.items():
        h = health.get(capability_id)
        item = {
            "id": capability_id,
            "label": meta.get("label"),
            "surfaces": meta.get("surfaces", []),
            "integration_state": meta.get("integration_state"),
            "authority": meta.get("authority"),
            "reachable": h.get("reachable") if h else None,
            "healthy": h.get("healthy") if h else None,
            "http_status": h.get("http_status") if h else None,
            "latency_ms": h.get("latency_ms") if h else None,
            "reported_status": h.get("reported_status") if h else None,
            "error": h.get("error") if h else None,
        }
        items.append(item)
        seen.add(capability_id)

    for capability_id, h in health.items():
        if capability_id in seen:
            continue
        items.append(
            {
                "id": capability_id,
                "label": h.get("label"),
                "surfaces": [],
                "integration_state": "health-only",
                "authority": "internal read health",
                "reachable": h.get("reachable"),
                "healthy": h.get("healthy"),
                "http_status": h.get("http_status"),
                "latency_ms": h.get("latency_ms"),
                "reported_status": h.get("reported_status"),
                "error": h.get("error"),
            }
        )

    items.sort(key=lambda x: str(x.get("label") or x.get("id") or ""))
    summary = {
        "total": len(items),
        "reachable": sum(1 for item in items if item.get("reachable") is True),
        "healthy": sum(1 for item in items if item.get("healthy") is True),
        "configured_offline": sum(1 for item in items if item.get("integration_state") == "configured-offline"),
        "unknown_health": sum(1 for item in items if item.get("reachable") is None),
    }
    return {
        "schema": "vmi.capability-readiness.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "items": items,
        "internal_addresses_exposed": False,
        "internal_paths_exposed": False,
        "authority": {
            "health_read_only": True,
            "startup_permitted": False,
            "shutdown_permitted": False,
            "execution_permitted": False,
            "external_actions_executed": 0,
        },
    }
