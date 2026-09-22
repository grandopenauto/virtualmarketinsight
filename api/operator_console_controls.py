from __future__ import annotations

import hashlib
import hmac
import os

from api.operator_console import CONSOLE_HTML


def _secret(secret: str | None = None) -> str:
    value = secret or os.getenv("VMI_OPERATOR_KEY", "")
    if not value:
        raise RuntimeError("operator_key_not_configured")
    return value


def csrf_token(session_token: str, secret: str | None = None) -> str:
    return hmac.new(
        _secret(secret).encode("utf-8"),
        ("vmi-console-csrf:" + session_token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_csrf(session_token: str, supplied: str | None, secret: str | None = None) -> bool:
    if not session_token or not supplied:
        return False
    try:
        expected = csrf_token(session_token, secret)
    except RuntimeError:
        return False
    return hmac.compare_digest(expected, supplied)


CONTROL_SCRIPT = r"""
<style>
.review-control{margin-top:14px;background:#fff;border:1px solid #dce9f8;border-radius:18px;padding:18px;box-shadow:0 12px 34px rgba(11,47,97,.05)}
.review-control h3{margin:0 0 8px}.review-form{display:grid;grid-template-columns:1fr 1fr;gap:10px}.review-form select,.review-form input,.review-form textarea{width:100%;border:1px solid #cbdced;border-radius:10px;padding:10px;font:inherit;background:#fff}.review-form textarea{grid-column:1/-1;min-height:86px;resize:vertical}.review-form .full{grid-column:1/-1}.review-form button{grid-column:1/-1;border:0;border-radius:10px;padding:12px;background:#1769e0;color:#fff;font-weight:800;cursor:pointer}.review-form button:disabled{opacity:.55;cursor:not-allowed}.control-note{font-size:13px;color:#63758d;margin-bottom:12px}.control-status{min-height:20px;margin-top:10px;font-size:13px}.control-status.ok{color:#147a46}.control-status.err{color:#b42318}@media(max-width:620px){.review-form{grid-template-columns:1fr}}
</style>
<script>
let consoleCsrf='';
async function loadConsoleCsrf(){if(consoleCsrf)return consoleCsrf;const r=await fetch('/operator/api/session',{credentials:'same-origin'});if(r.status===401){location.href='/operator/login';throw new Error('unauthorized')}if(!r.ok)throw new Error('csrf unavailable');const d=await r.json();consoleCsrf=d.csrf_token;return consoleCsrf}
function mountReviewControls(recordId){const view=document.getElementById('view');if(!view||!recordId)return;const old=document.getElementById('human-review-control');if(old)old.remove();const box=document.createElement('section');box.id='human-review-control';box.className='review-control';box.innerHTML=`<h3>Record Human Review Event</h3><div class="control-note">This records your review direction only. It does not approve, authorize, dispatch, trade, message, spend, or execute anything.</div><form class="review-form" id="review-event-form"><select id="review-decision"><option value="request_more_evidence">Request more evidence</option><option value="resolve_capability_gap">Resolve capability gap</option><option value="prepare_bounded_action">Prepare bounded action</option><option value="stop">Stop review path</option></select><input id="review-scope" placeholder="Scope (optional)"><textarea id="review-note" placeholder="Review note (optional)"></textarea><button id="review-submit">Record review event</button></form><div id="review-status" class="control-status"></div>`;const timeline=view.querySelector('.timeline');if(timeline)view.insertBefore(box,timeline);else view.appendChild(box);box.querySelector('#review-event-form').addEventListener('submit',async(e)=>{e.preventDefault();const status=box.querySelector('#review-status');const btn=box.querySelector('#review-submit');status.textContent='';status.className='control-status';btn.disabled=true;try{const csrf=await loadConsoleCsrf();const body={decision:box.querySelector('#review-decision').value,reviewer_label:'operator-console',note:box.querySelector('#review-note').value,scope:box.querySelector('#review-scope').value};const r=await fetch('/operator/api/cases/'+encodeURIComponent(recordId)+'/review-event',{method:'POST',headers:{'content-type':'application/json','x-vmi-csrf':csrf},credentials:'same-origin',body:JSON.stringify(body)});if(!r.ok){const x=await r.json().catch(()=>({}));throw new Error(x.detail||'Review event rejected')}status.textContent='Review event recorded. Refreshing current gate…';status.className='control-status ok';setTimeout(()=>loadCase(recordId),250)}catch(err){status.textContent=String(err.message||err);status.className='control-status err'}finally{btn.disabled=false}})}
const _v23LoadCase=loadCase;loadCase=async function(id){await _v23LoadCase(id);mountReviewControls(id)};setTimeout(()=>{if(selected)mountReviewControls(selected)},600);
</script>
"""

CONSOLE_HTML_V24 = CONSOLE_HTML.replace("</body>", CONTROL_SCRIPT + "</body>")
