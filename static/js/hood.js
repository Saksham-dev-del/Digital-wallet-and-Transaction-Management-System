// "Under the hood": a live view of what the server is doing - the last payment's step-by-step trace,
// lock / cache / queue counters and the audit-log chain. Docked on wide screens, a sheet on phones.
import { api } from './api.js';
import { state, bus } from './state.js';
import { html, paint, $ } from './ui.js';
import { openSheet } from './sheet.js';

const stepsHtml = (steps) => html`<ul class="hood-steps">${steps.map((s, i) => html`<li style="animation-delay:${i * 60}ms"><span class="lay lay-${s.layer}">${s.layer}</span><span class="ttl">${s.title}${s.detail ? html`<span class="det">${s.detail}</span>` : ''}</span><span class="ms">${s.t_ms}ms</span></li>`)}</ul>`;

export function hoodPanel(host) {
  paint(host, html`
    <section class="hood" aria-label="Under the hood">
      <h2><span class="live" aria-hidden="true"></span>Under the hood</h2>
      <p class="sub">Live from the server running this app.</p>
      <h3>Right now</h3><div class="hood-grid" id="hood-stats"></div>
      <h3 id="hood-last">Last action</h3><div id="hood-trace"></div>
      <h3>Audit log</h3><div id="hood-audit" class="small"></div>
      <button class="btn block" data-go="lab/overview" style="margin-top:18px">Open the lab console</button>
    </section>`);

  function drawTrace() {
    const t = state.lastTrace;
    $('#hood-last', host).textContent = t ? `Last action: ${t.title}` : 'Last action';
    paint($('#hood-trace', host), t ? stepsHtml(t.steps) : html`<p class="empty-note">Make a payment and every step the server takes shows up here: AI check, wallet locks, database transaction, cache and audit log.</p>`);
  }
  async function refresh() {
    if (document.hidden) return;
    try {
      const o = await api('/os/overview'), c = o.cache, lk = o.locks.stats, sc = o.scheduler;
      const stats = [['Locks taken', lk.acquired || 0], ['Had to wait', lk.contended || 0], ['Cache hit rate', c.hit_ratio == null ? 'n/a' : Math.round(c.hit_ratio * 100) + '%'],
        ['Queued jobs', sc.queue_length], ['Threads', o.system.threads.length], ['Cache', c.kind === 'redis' ? 'Redis' : 'LRU']];
      paint($('#hood-stats', host), html`${stats.map(([k, v]) => html`<div class="hood-stat"><b>${v}</b><span>${k}</span></div>`)}`);
    } catch { /* offline or signed out */ }
    try {
      const v = await api('/os/audit/verify');
      paint($('#hood-audit', host), html`<span style="color:${v.ok ? '#58D8A2' : '#FF8E7E'}">${v.ok ? 'Chain intact' : 'Chain broken'}</span> · ${v.entries} ${v.entries === 1 ? 'record' : 'records'}${v.head ? html`<br><span style="font:12px var(--mono);color:#9AA2D2">head ${v.head.slice(0, 18)}…</span>` : ''}`);
    } catch { /* ignore */ }
  }
  const onTrace = () => { drawTrace(); refresh(); };
  bus.addEventListener('trace', onTrace);
  drawTrace();
  refresh();
  const timer = setInterval(refresh, 3000);
  return () => { clearInterval(timer); bus.removeEventListener('trace', onTrace); };
}

export function openHoodSheet() {
  let dispose = null;
  openSheet(html`<div id="hood-host"></div>`, { label: 'Under the hood', onClose: () => { if (dispose) dispose(); }, onMount: (body) => { dispose = hoodPanel($('#hood-host', body)); } });
}
