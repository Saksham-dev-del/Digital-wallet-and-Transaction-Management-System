import { api, downloadFile } from '../api.js';
import { html, paint, $, $$, dayLabel, debounce, toast, errText, busy } from '../ui.js';
import { icon } from '../icons.js';
import { txnRow } from '../rows.js';
import { go } from '../state.js';

const FILTERS = [['all', 'All', {}], ['out', 'Sent', { direction: 'out' }], ['in', 'Received', { direction: 'in' }], ['topup', 'Added', { type: 'TOPUP' }],
  ['otp', 'Awaiting OTP', { status: 'PENDING_OTP' }], ['held', 'Held', { status: 'BLOCKED' }], ['failed', 'Failed', { status: 'FAILED' }]];
const PAGE = 25;

export async function mount(host) {
  const s = { filter: 'all', q: '', rows: [], total: 0 };
  paint(host, html`
    <div class="bar"><h1>Activity</h1><button class="icon-btn" id="export" aria-label="Download statement">${icon('download')}</button></div>
    <div class="view">
      <div class="search">${icon('search')}<input class="input" id="q" type="search" placeholder="Search name, note or reference" aria-label="Search activity"></div>
      <div class="chips" id="chips" style="margin-top:12px">${FILTERS.map(([id, label]) => html`<button class="chip" data-f="${id}" aria-pressed="${String(id === 'all')}">${label}</button>`)}</div>
      <div id="list" aria-live="polite"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>
      <div id="more" style="margin-top:14px;text-align:center"></div>
    </div>`);
  const params = (offset) => new URLSearchParams({ limit: PAGE, offset, ...Object.fromEntries(Object.entries(FILTERS.find((f) => f[0] === s.filter)[2])), ...(s.q ? { q: s.q } : {}) });

  function draw() {
    const groups = [];
    for (const t of s.rows) {
      const d = dayLabel(t.created_at), g = groups[groups.length - 1];
      if (g && g.d === d) g.items.push(t); else groups.push({ d, items: [t] });
    }
    paint($('#list', host), s.rows.length
      ? html`${groups.map((g) => html`<div class="day">${g.d}</div><ul class="list">${g.items.map(txnRow)}</ul>`)}`
      : html`<div class="empty"><h3>${s.q || s.filter !== 'all' ? 'Nothing matches' : 'No activity yet'}</h3><p>${s.q || s.filter !== 'all' ? 'Try a different search or filter.' : 'Your payments will show up here.'}</p>${!s.q && s.filter === 'all' ? html`<button class="btn" data-go="add">Add money</button>` : ''}</div>`);
    paint($('#more', host), s.rows.length < s.total ? html`<button class="btn soft" id="older">Show older</button><p class="hint" style="margin-top:8px">Showing ${s.rows.length} of ${s.total}</p>` : (s.total ? html`<p class="hint">That's everything · ${s.total} in total</p>` : ''));
    const older = $('#older', host);
    if (older) older.addEventListener('click', () => busy(older, () => load(false)));
  }
  async function load(reset = true) {
    try {
      const d = await api('/transactions?' + params(reset ? 0 : s.rows.length));
      s.rows = reset ? d.transactions : s.rows.concat(d.transactions); s.total = d.total; draw();
    } catch (e) { paint($('#list', host), html`<p class="err">${errText(e)}</p>`); }
  }
  host.addEventListener('click', (e) => { const r = e.target.closest('[data-ref]'); if (r) go('txn/' + r.dataset.ref); });
  $('#chips', host).addEventListener('click', (e) => {
    const b = e.target.closest('[data-f]'); if (!b) return;
    s.filter = b.dataset.f; $$('#chips .chip', host).forEach((c) => c.setAttribute('aria-pressed', String(c === b))); load();
  });
  $('#q', host).addEventListener('input', debounce((e) => { s.q = e.target.value.trim(); load(); }, 350));
  $('#export', host).addEventListener('click', (e) => busy(e.currentTarget, async () => {
    try { await downloadFile('/transactions/export.csv?' + new URLSearchParams({ ...Object.fromEntries(Object.entries(FILTERS.find((f) => f[0] === s.filter)[2])), ...(s.q ? { q: s.q } : {}) }), 'wallet-statement.csv'); toast('Statement downloaded.', 'good'); }
    catch (ex) { toast(errText(ex), 'bad'); }
  }));
  await load();
}
