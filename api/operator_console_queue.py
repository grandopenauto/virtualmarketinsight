from __future__ import annotations

from api.operator_console_readiness import CONSOLE_HTML_V25

QUEUE_SCRIPT = r"""
<style>
.attn{margin:14px 0 18px;padding:12px;border:1px solid #dce9f8;border-radius:14px;background:#fff}.attn h4{margin:0 0 8px}.attn-summary{font-size:12px;color:#63758d;margin-bottom:8px}.attn-item{display:block;width:100%;text-align:left;border:0;border-top:1px solid #eef3f8;background:transparent;padding:9px 0;cursor:pointer;color:#10233f}.attn-item:first-of-type{border-top:0}.attn-item strong{display:block}.attn-item small{color:#63758d}.posture-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;background:#1769e0}.posture-dot.blocked{background:#b42318}.posture-dot.attention_required{background:#a15c00}.posture-dot.clear{background:#147a46}.posture-dot.clear_with_history{background:#4d7aa9}
</style>
<script>
async function loadActionQueue(){const aside=document.querySelector('aside');if(!aside)return;let box=document.getElementById('attention-queue');if(!box){box=document.createElement('div');box.id='attention-queue';box.className='attn';const cases=document.getElementById('cases');aside.insertBefore(box,cases)}box.innerHTML='<h4>Current Action Queue</h4><div class="attn-summary">Checking governance posture…</div>';try{const r=await fetch('/operator/api/action-queue',{credentials:'same-origin'});if(r.status===401){location.href='/operator/login';return}if(!r.ok)throw new Error('queue unavailable');const d=await r.json();const top=d.items.slice(0,5).map(x=>`<button class="attn-item" data-id="${esc(x.current_record_id)}"><strong><span class="posture-dot ${esc(x.posture)}"></span>${esc(x.intent_label||'VMI Review')}</strong><small>${esc(x.posture)} · ${esc(x.unresolved_gap_count)} gaps · gen ${esc(x.generation)}</small></button>`).join('');box.innerHTML=`<h4>Current Action Queue</h4><div class="attn-summary">${esc(d.summary.attention_required)} attention · ${esc(d.summary.blocked)} blocked · ${esc(d.summary.total)} total</div>${top||'<div class="muted">No cases.</div>'}`;box.querySelectorAll('.attn-item').forEach(b=>b.onclick=()=>loadCase(b.dataset.id))}catch(_){box.innerHTML='<h4>Current Action Queue</h4><div class="muted">Queue unavailable.</div>'}}
setTimeout(loadActionQueue,500);
</script>
"""

CONSOLE_HTML_V26 = CONSOLE_HTML_V25.replace("</body>", QUEUE_SCRIPT + "</body>")
