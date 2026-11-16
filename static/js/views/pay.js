import { api } from '../api.js';
import { state, go, refreshWallet } from '../state.js';
import { html, paint, $, $$, money, avatar, CATEGORIES, debounce, errText, dateTime } from '../ui.js';
import { icon } from '../icons.js';
import { openSheet } from '../sheet.js';
import { keypadHtml, bindAmount } from '../keypad.js';
import { reviewPayment } from '../flow.js';
import { showDone } from '../done.js';

export async function mount(host, ctx) {
  return ctx.params[0] ? amountScreen(host, ctx) : picker(host, ctx);
}

// ------------------------------------------------------------------ who to pay
async function picker(host, ctx) {
  paint(host, html`
    <div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Pay</h1></div>
    <div class="view">
      <div class="search">${icon('search')}<input class="input" id="q" type="search" placeholder="Name, wallet ID, email or phone" autocomplete="off" aria-label="Search people and merchants" value="${ctx.query.get('q') || ''}"></div>
      <div id="found"></div>
      <div id="lists"><div class="skel"></div><div class="skel"></div></div>
    </div>`);
  const [rc, mc] = await Promise.all([api('/recipients/recent').catch(() => ({ contacts: [] })), api('/merchants').catch(() => ({ merchants: [] }))]);
  const people = rc.contacts.filter((c) => !c.merchant), merchants = mc.merchants;
  const input = $('#q', host);

  const draw = () => {
    const q = input.value.trim().toLowerCase();
    const match = (x) => !q || x.name.toLowerCase().includes(q) || x.wallet_code.toLowerCase().includes(q);
    const p = people.filter(match), m = merchants.filter(match);
    paint($('#lists', host), html`
      ${p.length ? html`<div class="group-label">${q ? 'People' : 'Recent'}</div><ul class="list">${p.map((c) => html`<li><button class="row" data-to="${c.wallet_code}">${avatar(c.name)}<div style="min-width:0"><div class="t">${c.name}</div><div class="s mono">${c.wallet_code}</div></div>${icon('chevR')}</button></li>`)}</ul>` : ''}
      ${m.length ? html`<div class="group-label">Merchants</div><div class="merchants">${m.map((c) => html`<button class="person" data-to="${c.wallet_code}" aria-label="Pay ${c.name}">${avatar(c.name, { size: 56, merchant: true })}<span>${c.name}</span></button>`)}</div>` : ''}
      ${!p.length && !m.length && !q ? html`<div class="empty"><h3>Nobody yet</h3><p>Type a wallet ID or email above to pay someone new.</p></div>` : ''}`);
  };
  const lookup = debounce(async () => {
    const q = input.value.trim();
    const looksLikeId = /@|^\+?\d[\d\s-]{8,}$/.test(q);
    if (!looksLikeId) { paint($('#found', host), ''); return; }
    try {
      const r = await api('/recipients/lookup?q=' + encodeURIComponent(q));
      paint($('#found', host), html`<div class="group-label">Found</div><ul class="list"><li><button class="row" data-to="${r.wallet_code}">${avatar(r.name, { merchant: r.merchant })}<div style="min-width:0"><div class="t">${r.name}</div><div class="s mono">${r.wallet_code}</div></div><span class="tag ok">Pay</span></button></li></ul>`);
    } catch (e) { paint($('#found', host), html`<p class="err" style="margin-top:12px">${errText(e)}</p>`); }
  }, 400);
  input.addEventListener('input', () => { draw(); lookup(); });
  host.addEventListener('click', (e) => { const t = e.target.closest('[data-to]'); if (t) go('pay/' + encodeURIComponent(t.dataset.to)); });
  draw(); if (input.value) lookup();
  if (!ctx.query.get('q')) input.focus({ preventScroll: true });
}

// ------------------------------------------------------------------ how much
async function amountScreen(host, ctx) {
  const code = ctx.params[0];
  paint(host, html`<div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Pay</h1></div><div class="view"><div class="skel"></div></div>`);
  let rec;
  try { rec = await api('/recipients/lookup?q=' + encodeURIComponent(code)); }
  catch (e) { paint(host, html`<div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Pay</h1></div><div class="view"><div class="empty"><h3>Can't pay that wallet</h3><p>${errText(e)}</p><button class="btn" data-go="pay">Choose someone else</button></div></div>`); return; }
  await refreshWallet().catch(() => {});
  const balance = state.wallet ? state.wallet.balance_paise : 0;
  let chosen = '', predicted = '', lastPreview = null;

  paint(host, html`
    <div class="pay-screen">
      <div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Pay</h1></div>
      <div class="grow-body">
        <div class="payee">${avatar(rec.name, { size: 64, merchant: rec.merchant })}<b>${rec.name}</b><span class="muted small mono">${rec.wallet_code}</span></div>
        <div class="amt-display" id="amt" role="status"></div>
        <div class="note-row"><input id="note" maxlength="80" placeholder="Add a note" value="${ctx.query.get('note') || ''}" aria-label="Note"><button class="cat-chip" id="cat" type="button">${icon('sparkle')}<span id="cat-text">Category</span></button></div>
        <div class="hintline" id="hint" aria-live="polite"></div>
      </div>
      <div class="pay-foot">${keypadHtml()}<div class="from">Paying from Smart Wallet · Balance ${money(balance)}</div><button class="btn block" id="go" disabled>Pay</button></div>
    </div>`);
  const noteEl = $('#note', host), goBtn = $('#go', host), hint = $('#hint', host), catText = $('#cat-text', host);

  const setHint = (cls, ic, text) => { hint.className = 'hintline ' + cls; hint.innerHTML = text ? `${ic ? icon(ic).s : ''}<span></span>` : ''; if (text) hint.querySelector('span').textContent = text; };
  const refreshPreview = debounce(async () => {
    const amt = pad.value;
    if (!(parseFloat(amt) > 0)) { setHint('', '', ''); return; }
    try {
      const p = await api('/wallet/transfer/preview', { method: 'POST', body: { to: rec.wallet_code, amount: amt, note: noteEl.value } });
      if (amt !== pad.value) return;
      lastPreview = p; predicted = p.category.category;
      if (!chosen) catText.textContent = predicted;
      if (p.balance_after_paise < 0) setHint('bad', 'alert', `That is more than your balance of ${money(balance)}.`);
      else if (p.outcome === 'INSTANT') setHint('ok', 'shield', 'AI shield: cleared, goes through instantly');
      else if (p.outcome === 'OTP') setHint('warn', 'lock', 'You will be asked for an OTP');
      else setHint('bad', 'alert', 'AI shield: this looks risky and would be held');
      goBtn.disabled = p.balance_after_paise < 0;
    } catch (e) { setHint('bad', 'alert', errText(e)); }
  }, 450);

  const pad = bindAmount(host, { onChange: (v) => {
    const ok = parseFloat(v) > 0;
    goBtn.disabled = !ok; goBtn.textContent = ok ? `Pay ${money(Math.round(parseFloat(v) * 100))}` : 'Pay';
    if (!ok) { setHint('', '', ''); lastPreview = null; } else { setHint('', '', 'Checking…'); refreshPreview(); }
  } });
  noteEl.addEventListener('input', () => { if (parseFloat(pad.value) > 0) refreshPreview(); });
  if (ctx.query.get('amount')) pad.set(ctx.query.get('amount'));

  $('#cat', host).addEventListener('click', () => {
    openSheet(html`<h2>Category</h2><p class="muted small">The AI learns from your choice.</p><ul class="list" style="margin-top:12px;box-shadow:none;background:var(--surface-2)">${CATEGORIES.map((c) => html`<li><button class="row" data-cat="${c}" style="grid-template-columns:minmax(0,1fr) auto"><span class="t">${c}</span>${c === (chosen || predicted) ? icon('check') : ''}</button></li>`)}</ul>`,
    { label: 'Choose a category', onMount: (b, h) => b.addEventListener('click', (e) => { const r = e.target.closest('[data-cat]'); if (!r) return; chosen = r.dataset.cat; catText.textContent = chosen; h.close(); }) });
  });

  goBtn.addEventListener('click', async () => {
    const res = await reviewPayment({ kind: 'TRANSFER', recipient: rec, amount: pad.value, note: noteEl.value.trim(), category: chosen });
    if (!res) return;
    await refreshWallet().catch(() => {});
    showDone(host, res, { title: `Paid to ${rec.name}`, sub: res.created_at ? dateTime(res.created_at) : '', who: rec.name });
  });
  return () => pad.dispose();
}
