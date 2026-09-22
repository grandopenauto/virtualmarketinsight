from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from typing import Any

from pydantic import BaseModel, Field

from api.decision_dossiers import build_decision_dossier
from api.governance_monitor import evaluate_governance
from api.review_ledger import get_record, ledger_path

SESSION_COOKIE = "vmi_operator_session"
SESSION_TTL_SECONDS = 8 * 60 * 60


class OperatorLogin(BaseModel):
    operator_key: str = Field(min_length=8, max_length=2048)


def _operator_secret() -> str:
    value = os.getenv("VMI_OPERATOR_KEY", "")
    if not value:
        raise RuntimeError("operator_key_not_configured")
    return value


def _session_signature(ts: int, nonce: str, secret: str) -> str:
    material = f"{ts}:{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


def issue_session_token(secret: str | None = None, now: int | None = None) -> str:
    key = secret or _operator_secret()
    ts = int(now or time.time())
    nonce = secrets.token_urlsafe(18)
    signature = _session_signature(ts, nonce, key)
    return f"{ts}.{nonce}.{signature}"


def validate_session_token(
    token: str | None,
    secret: str | None = None,
    now: int | None = None,
) -> bool:
    if not token:
        return False
    try:
        raw_ts, nonce, supplied = token.split(".", 2)
        ts = int(raw_ts)
    except (ValueError, TypeError):
        return False
    current = int(now or time.time())
    if ts > current + 60 or current - ts > SESSION_TTL_SECONDS:
        return False
    try:
        expected = _session_signature(ts, nonce, secret or _operator_secret())
    except RuntimeError:
        return False
    return hmac.compare_digest(supplied, expected)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ledger_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _review_graph() -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, str]]:
    records: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}
    parents: dict[str, str] = {}
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM review_records ORDER BY sequence ASC").fetchall()
    for row in rows:
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        cycle = payload.get("review_cycle", {}) or {}
        parent = cycle.get("parent_record_id")
        item["parent_record_id"] = parent
        item["generation"] = int(cycle.get("generation", 0) or 0)
        packet = payload.get("decision_packet", {}) or {}
        intent = packet.get("intent", {}) or {}
        item["intent_label"] = intent.get("label") or intent.get("resolved_surface") or "VMI Review"
        query = str(intent.get("query") or "").strip()
        item["query_preview"] = query[:180] + ("…" if len(query) > 180 else "")
        records[item["record_id"]] = item
        if parent:
            parents[item["record_id"]] = str(parent)
            children.setdefault(str(parent), []).append(item["record_id"])
    return records, children, parents


def _root(record_id: str, parents: dict[str, str]) -> str:
    current = record_id
    seen: set[str] = set()
    while current in parents:
        if current in seen:
            break
        seen.add(current)
        current = parents[current]
    return current


def _descendants(root_id: str, children: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    stack = [root_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop(0)
        if current in seen:
            continue
        seen.add(current)
        found.append(current)
        stack.extend(children.get(current, []))
    return found


def list_operator_cases(limit: int = 50) -> list[dict[str, Any]]:
    records, children, parents = _review_graph()
    roots = [rid for rid in records if rid not in parents]
    cases: list[dict[str, Any]] = []
    for root_id in roots:
        lineage = [records[rid] for rid in _descendants(root_id, children) if rid in records]
        if not lineage:
            continue
        latest = max(lineage, key=lambda x: int(x.get("sequence", 0)))
        cases.append(
            {
                "root_record_id": root_id,
                "current_record_id": latest["record_id"],
                "request_id": latest.get("request_id"),
                "intent_label": latest.get("intent_label") or "VMI Review",
                "query_preview": latest.get("query_preview") or "",
                "generation": int(latest.get("generation", 0) or 0),
                "generation_count": max(int(x.get("generation", 0) or 0) for x in lineage) + 1,
                "state": latest.get("state"),
                "created_at": latest.get("created_at"),
                "sequence": int(latest.get("sequence", 0)),
            }
        )
    cases.sort(key=lambda x: x["sequence"], reverse=True)
    for case in cases:
        case.pop("sequence", None)
    return cases[: max(1, min(int(limit), 100))]


def _available_actions(dossier: dict[str, Any], governance: dict[str, Any]) -> list[dict[str, Any]]:
    records = dossier.get("artifacts", {}).get("review_records", []) or []
    events = dossier.get("artifacts", {}).get("review_events", []) or []
    if not records:
        return []
    latest = max(records, key=lambda x: int(x.get("sequence", 0)))
    current_record_id = str(latest.get("record_id") or "")
    current_events = [e for e in events if str(e.get("record_id") or "") == current_record_id]
    latest_event = max(current_events, key=lambda x: int(x.get("sequence", 0)), default=None)
    if not latest_event:
        return [
            {
                "action": "record_human_review",
                "label": "Record human review",
                "status": "available",
                "reason": "The current review generation has not received a human review event yet.",
            }
        ]

    decision = str(latest_event.get("decision") or "")
    mapping = {
        "request_more_evidence": (
            "prepare_bounded_evidence_action",
            "Prepare bounded evidence action",
            "A new read-only evidence step may be prepared, then separately authorized.",
        ),
        "resolve_capability_gap": (
            "resolve_capability_gap",
            "Resolve capability gap",
            "Document or resolve the selected gap before further consequential preparation.",
        ),
        "prepare_bounded_action": (
            "prepare_bounded_action",
            "Prepare bounded action",
            "A bounded packet may be prepared; it still requires a separate human authorization.",
        ),
        "stop": (
            "none",
            "Review path stopped",
            "No further action is available from this review event.",
        ),
    }
    action, label, reason = mapping.get(
        decision,
        ("human_review_required", "Human review required", governance.get("current_human_gate") or "Human review required."),
    )
    return [{"action": action, "label": label, "status": "available" if action != "none" else "stopped", "reason": reason}]


def build_console_case(record_id: str) -> dict[str, Any]:
    dossier = build_decision_dossier(record_id)
    governance = evaluate_governance(record_id)
    records = dossier.get("artifacts", {}).get("review_records", []) or []
    latest = max(records, key=lambda x: int(x.get("sequence", 0)), default=None)
    current_record_id = str(latest.get("record_id")) if latest else record_id
    current_full = get_record(current_record_id, include_payload=True)
    current_packet = ((current_full or {}).get("payload", {}).get("decision_packet", {}) or {})
    intent = current_packet.get("intent", {}) or {}
    gaps = current_packet.get("gaps", []) or []

    findings = [
        {
            "severity": item.get("severity"),
            "code": item.get("code"),
            "detail": item.get("detail"),
            "artifact_id": item.get("artifact_id"),
            "count": item.get("count"),
        }
        for item in governance.get("findings", [])
    ]
    timeline = [
        {k: v for k, v in item.items() if k in {"created_at", "type", "id", "record_id", "state", "status", "decision", "action_kind", "target_capability", "capability_id", "contract_id", "operation", "http_status", "generation", "expires_at"}}
        for item in dossier.get("timeline", [])
    ]

    return {
        "schema": "vmi.operator-console-case.v1",
        "root_record_id": dossier.get("root_record_id"),
        "current_record_id": current_record_id,
        "generation_count": dossier.get("generation_count", 0),
        "intent": {
            "label": intent.get("label") or intent.get("resolved_surface") or "VMI Review",
            "resolved_surface": intent.get("resolved_surface"),
            "query": intent.get("query"),
        },
        "posture": governance.get("posture"),
        "integrity_ok": governance.get("integrity_ok"),
        "unresolved_gap_count": governance.get("unresolved_gap_count", len(gaps)),
        "current_human_gate": governance.get("current_human_gate"),
        "available_actions": _available_actions(dossier, governance),
        "findings": findings,
        "counts": dossier.get("counts", {}),
        "timeline": timeline,
        "integrity_checks": dossier.get("integrity", {}).get("checks", {}),
        "authority": {
            "console_view_only": True,
            "automatic_advancement_permitted": False,
            "approval_authority": False,
            "execution_authority": False,
            "dispatch_authority": False,
            "external_actions_executed": 0,
        },
    }


LOGIN_HTML = """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>VMI Operator Login</title>
<style>body{margin:0;font-family:Inter,system-ui,sans-serif;background:#f4f9ff;color:#10233f;min-height:100vh;display:grid;place-items:center}.card{width:min(440px,calc(100% - 36px));background:#fff;border:1px solid #dce9f8;border-radius:24px;padding:32px;box-shadow:0 24px 70px rgba(10,47,97,.12)}h1{margin:0 0 8px;font-size:28px}.eyebrow{color:#1769e0;font-weight:800;letter-spacing:.08em;text-transform:uppercase;font-size:12px}.muted{color:#63758d;line-height:1.55}input{width:100%;box-sizing:border-box;margin:18px 0 12px;padding:14px 16px;border:1px solid #cbdced;border-radius:12px;font:inherit}button{width:100%;padding:14px;border:0;border-radius:12px;background:#1769e0;color:white;font-weight:800;cursor:pointer}.error{min-height:20px;color:#b42318;font-size:14px;margin-top:10px}</style></head>
<body><main class=\"card\"><div class=\"eyebrow\">Virtual Market Insight</div><h1>Operator Console</h1><p class=\"muted\">Protected governance and decision-lineage view. The operator key is exchanged for a short-lived Secure/HttpOnly session and is not stored by the page.</p><form id=\"f\"><input id=\"k\" type=\"password\" autocomplete=\"current-password\" placeholder=\"Operator key\" required><button>Enter Console</button><div id=\"e\" class=\"error\"></div></form></main>
<script>document.getElementById('f').addEventListener('submit',async(e)=>{e.preventDefault();const box=document.getElementById('e');box.textContent='';const k=document.getElementById('k');try{const r=await fetch('/operator/session',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({operator_key:k.value}),credentials:'same-origin'});k.value='';if(!r.ok){box.textContent='Access denied.';return}location.href='/operator/console'}catch(_){box.textContent='Console unavailable.'}});</script></body></html>"""


CONSOLE_HTML = """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>VMI Operator Console</title>
<style>:root{--ink:#10233f;--muted:#63758d;--blue:#1769e0;--bg:#f5faff;--panel:#fff;--line:#dce9f8;--navy:#0b2f61;--warn:#a15c00;--bad:#b42318;--ok:#147a46}*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;background:radial-gradient(circle at 80% 0,#dceeff 0,transparent 35%),var(--bg);color:var(--ink)}header{height:70px;background:rgba(255,255,255,.92);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 24px;position:sticky;top:0;z-index:5}header b{font-size:18px}button{font:inherit}.logout{border:1px solid var(--line);background:white;border-radius:10px;padding:9px 12px;cursor:pointer}.layout{display:grid;grid-template-columns:300px 1fr;min-height:calc(100vh - 70px)}aside{border-right:1px solid var(--line);padding:20px;background:rgba(255,255,255,.72)}.cases{display:grid;gap:10px}.case{padding:14px;border:1px solid var(--line);background:#fff;border-radius:14px;cursor:pointer;text-align:left}.case.active{border-color:#78adf2;box-shadow:0 0 0 3px rgba(23,105,224,.08)}.case small,.muted{color:var(--muted)}main{padding:24px;max-width:1500px;width:100%}.hero{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:18px}.tag{display:inline-flex;padding:6px 9px;border-radius:999px;background:#edf5ff;color:var(--blue);font-weight:800;font-size:12px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}.metric,.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 12px 34px rgba(11,47,97,.05)}.metric strong{font-size:26px;display:block;margin-top:6px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.panel h3{margin:0 0 12px}.finding{border-top:1px solid #eef3f8;padding:10px 0}.finding:first-child{border-top:0}.finding .sev{font-size:11px;font-weight:900;text-transform:uppercase}.attention{color:var(--warn)}.block{color:var(--bad)}.info{color:var(--blue)}.action{padding:14px;border:1px solid #cfe0f4;background:#f7fbff;border-radius:12px}.timeline{margin-top:14px}.event{display:grid;grid-template-columns:175px 160px 1fr;gap:12px;padding:10px 0;border-top:1px solid #eef3f8;font-size:13px}.event:first-child{border-top:0}.ok{color:var(--ok)}.bad{color:var(--bad)}pre{white-space:pre-wrap}.empty{color:var(--muted);padding:18px 0}@media(max-width:950px){.layout{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid var(--line)}.cards,.grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.cards,.grid{grid-template-columns:1fr}.event{grid-template-columns:1fr}.hero{display:block}}</style></head>
<body><header><div><b>VMI Operator Console</b> <span class=\"muted\">Governed decision control plane</span></div><button class=\"logout\" id=\"logout\">Sign out</button></header><div class=\"layout\"><aside><div class=\"tag\">Decision cases</div><div id=\"cases\" class=\"cases\" style=\"margin-top:14px\"></div></aside><main><div id=\"view\" class=\"empty\">Loading governed case data…</div></main></div>
<script>
const esc=s=>String(s??'').replace(/[&<>\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[m]));
const fmt=s=>{if(!s)return '';try{return new Date(s).toLocaleString()}catch(_){return s}};
let selected='';
async function api(path){const r=await fetch(path,{credentials:'same-origin'});if(r.status===401){location.href='/operator/login';throw new Error('unauthorized')}if(!r.ok)throw new Error('request failed');return r.json()}
async function loadCases(){const d=await api('/operator/api/cases');const box=document.getElementById('cases');box.innerHTML=d.items.map(x=>`<button class=\"case ${selected===x.current_record_id?'active':''}\" data-id=\"${esc(x.current_record_id)}\"><strong>${esc(x.intent_label)}</strong><div><small>Gen ${x.generation} · ${esc(x.state)}</small></div><div><small>${esc(x.query_preview)}</small></div></button>`).join('')||'<div class=\"empty\">No review cases yet.</div>';box.querySelectorAll('.case').forEach(b=>b.onclick=()=>loadCase(b.dataset.id));if(!selected&&d.items[0])await loadCase(d.items[0].current_record_id)}
async function loadCase(id){selected=id;const d=await api('/operator/api/cases/'+encodeURIComponent(id));await loadCasesOnly();const v=document.getElementById('view');const f=d.findings.map(x=>`<div class=\"finding\"><div class=\"sev ${esc(x.severity)}\">${esc(x.severity)} · ${esc(x.code)}</div><div>${esc(x.detail)}</div></div>`).join('')||'<div class=\"empty\">No governance findings.</div>';const a=d.available_actions.map(x=>`<div class=\"action\"><strong>${esc(x.label)}</strong><div class=\"muted\">${esc(x.reason)}</div><small>Control state: ${esc(x.status)} · console is view-only</small></div>`).join('');const t=d.timeline.slice().reverse().map(x=>`<div class=\"event\"><div>${esc(fmt(x.created_at))}</div><strong>${esc(x.type)}</strong><div>${esc(x.decision||x.action_kind||x.operation||x.state||x.status||x.id)}</div></div>`).join('');v.className='';v.innerHTML=`<div class=\"hero\"><div><div class=\"tag\">${esc(d.posture)}</div><h1>${esc(d.intent.label)}</h1><p class=\"muted\">${esc(d.intent.query||'No query text recorded.')}</p></div><div><strong class=\"${d.integrity_ok?'ok':'bad'}\">${d.integrity_ok?'Integrity verified':'Integrity issue'}</strong><div class=\"muted\">${esc(d.current_record_id)}</div></div></div><div class=\"cards\"><div class=\"metric\">Generations<strong>${esc(d.generation_count)}</strong></div><div class=\"metric\">Unresolved gaps<strong>${esc(d.unresolved_gap_count)}</strong></div><div class=\"metric\">Timeline artifacts<strong>${esc(d.timeline.length)}</strong></div><div class=\"metric\">External actions<strong>0</strong></div></div><div class=\"grid\"><section class=\"panel\"><h3>Current human gate</h3><p>${esc(d.current_human_gate)}</p><h3>Available next control</h3>${a||'<div class=\"empty\">No current action.</div>'}</section><section class=\"panel\"><h3>Governance findings</h3>${f}</section></div><section class=\"panel timeline\"><h3>Decision lineage</h3>${t||'<div class=\"empty\">No timeline artifacts.</div>'}</section>`}
async function loadCasesOnly(){const d=await api('/operator/api/cases');const box=document.getElementById('cases');box.innerHTML=d.items.map(x=>`<button class=\"case ${selected===x.current_record_id?'active':''}\" data-id=\"${esc(x.current_record_id)}\"><strong>${esc(x.intent_label)}</strong><div><small>Gen ${x.generation} · ${esc(x.state)}</small></div><div><small>${esc(x.query_preview)}</small></div></button>`).join('')||'<div class=\"empty\">No review cases yet.</div>';box.querySelectorAll('.case').forEach(b=>b.onclick=()=>loadCase(b.dataset.id))}
document.getElementById('logout').onclick=async()=>{await fetch('/operator/session',{method:'DELETE',credentials:'same-origin'});location.href='/operator/login'};loadCases().catch(()=>document.getElementById('view').textContent='Console data unavailable.');
</script></body></html>"""
