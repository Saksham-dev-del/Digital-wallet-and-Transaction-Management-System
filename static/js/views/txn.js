import { api } from '../api.js';
import { state, go, refreshWallet } from '../state.js';
import { html, paint, $, money, avatar, dateTime, copyText, toast, errText, CATEGORIES } from '../ui.js';
import { icon } from '../icons.js';
import { openSheet } from '../sheet.js';
import { enterOtp } from '../flow.js';
import { statusTag } from '../rows.js';

const STEP = { PENDING: ['Payment started', ''], PENDING_OTP: ['Waiting for OTP', 'warn'], SUCCESS: ['Paid', 'ok'], FAILED: ['Failed', 'bad'], BLOCKED: ['Held for review', 'bad'] };

export async function mount(host, ctx) {
  const ref = ctx.params[0];
  const bar = html`<div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Payment</h1></div>`;
  paint(host, html`${bar}<div class="view"><div class="skel"></div><div class="skel"></div></div>`);
  let t, tl;
  try {
    [t, tl] = await Promise.all([api('/transactions/' + encodeURIComponent(ref)).then((r) => r.transaction),
      api(`/transactions/${encodeURIComponent(ref)}/timeline`).then((r) => r.timeline).catch(() => [])]);
  } catch (e) { paint(host, html`${bar}<div class="view"><div class="empty"><h3>Not found</h3><p>${errText(e)}</p><button class="btn" data-go="activity">Back to activity</button></div></div>`); return; }

  const out = t.direction === 'DEBIT', posted = t.status === 'SUCCESS';
  const who = t.counterparty ? t.counterparty.name : (t.type === 'TOPUP' ? 'Added to wallet' : 'Withdrawn to bank');
  const canTeach = out && t.type === 'TRANSFER' && posted;
  const statusLine = { SUCCESS: html`<span class="tag ok">${icon('check')} ${out ? 'Paid successfully' : 'Received'}</span>`, PENDING_OTP: html`<span class="tag warn">Waiting for your OTP</span>`,
    BLOCKED: html`<span class="tag bad">Held for review</span>`, FAILED: html`<span class="tag bad">Failed</span>`, PENDING: html`<span class="tag">Processing</span>` }[t.status];
  const steps = tl.map((x) => ({ label: STEP[x.status][0], cls: STEP[x.status][1], at: x.at }));
  if (t.risk && steps.length > 1) steps.splice(1, 0, { label: `AI shield checked it (risk ${t.risk.score}/100)`, cls: t.risk.level === 'HIGH' ? 'warn' : '', at: tl[0].at });
  const shareText = `Smart Wallet receipt\n${money(t.amount_paise)} ${out ? 'paid to' : 'received from'} ${who}\nReference ${t.txn_ref}\n${dateTime(t.created_at)}`;
  const tone = t.risk ? (t.risk.level === 'HIGH' ? 'high' : t.risk.level === 'MEDIUM' ? 'med' : '') : '';

  paint(host, html`
    <div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Payment</h1><button class="icon-btn" id="share" aria-label="Share receipt">${icon('share')}</button></div>
    <div class="view">
      <div class="hero-txn">${t.counterparty ? avatar(who, { size: 62 }) : html`<span class="av" style="--s:62px;--av-bg:var(--brand-tint);--av-fg:var(--brand)">${icon(t.type === 'TOPUP' ? 'add' : 'withdraw')}</span>`}
        <p class="muted">${out ? 'You paid' : 'You received'} · ${who}</p><div class="big ${posted && !out ? 'amt in' : ''}">${posted ? (out ? '−' : '+') : ''}${money(t.amount_paise)}</div><div>${statusLine}</div></div>
      ${t.status === 'PENDING_OTP' ? html`<button class="btn block" id="otp" style="margin-bottom:14px">Enter OTP to finish</button>` : ''}
      <div class="panel"><h3>Details</h3><dl class="kv" style="border:0;margin:0;padding:0">
        ${t.counterparty ? html`<dt>${out ? 'To' : 'From'}</dt><dd>${who}<br><small class="muted mono">${t.counterparty.wallet_code}</small></dd>` : ''}
        ${t.type === 'TRANSFER' ? html`<dt>Category</dt><dd>${canTeach ? html`<button class="cat-chip" id="cat" style="height:32px">${icon('tag')}${t.category}</button>` : t.category}</dd>` : ''}
        ${t.note ? html`<dt>Note</dt><dd>${t.note}</dd>` : ''}
        <dt>Reference</dt><dd class="mono"><button class="link-btn mono" id="copy">${t.txn_ref}</button></dd>
        <dt>When</dt><dd>${dateTime(t.created_at)}</dd>
        ${t.balance_after_paise != null ? html`<dt>Balance after</dt><dd class="num">${money(t.balance_after_paise)}</dd>` : ''}
        ${t.failure_reason ? html`<dt>Reason</dt><dd>${t.failure_reason}</dd>` : ''}</dl></div>
      ${steps.length ? html`<div class="panel"><h3>Journey</h3><ol class="vt">${steps.map((s) => html`<li class="${s.cls}"><b>${s.label}</b><span>${dateTime(s.at)}</span></li>`)}</ol></div>` : ''}
      ${t.risk ? html`<div class="panel"><h3>AI shield</h3><div class="row-flex between small"><span>Risk score</span><b>${t.risk.score}/100 · ${t.risk.level.toLowerCase()}</b></div><div class="meter ${tone}" style="margin-top:8px"><i style="width:${t.risk.score}%"></i></div>
        ${t.risk.reasons.length ? html`<ul class="reasons">${t.risk.reasons.map((r) => html`<li>${r.text}</li>`)}</ul>` : html`<p class="hint" style="margin-top:8px">Nothing unusual about this payment.</p>`}</div>` : ''}
      ${out && t.type === 'TRANSFER' && t.counterparty ? html`<button class="btn soft block" id="again" style="margin-top:14px">${icon('repeat')} Pay ${who.split(' ')[0]} again</button>` : ''}
    </div>`);

  $('#copy', host).addEventListener('click', async () => toast((await copyText(t.txn_ref)) ? 'Reference copied.' : 'Could not copy.'));
  $('#share', host).addEventListener('click', async () => {
    if (navigator.share) { try { await navigator.share({ title: 'Smart Wallet receipt', text: shareText }); return; } catch { /* cancelled */ } }
    toast((await copyText(shareText)) ? 'Receipt copied to clipboard.' : 'Could not copy.', 'good');
  });
  const again = $('#again', host);
  if (again) again.addEventListener('click', () => go('pay/' + encodeURIComponent(t.counterparty.wallet_code)));
  const otp = $('#otp', host);
  if (otp) otp.addEventListener('click', async () => { const r = await enterOtp({ txn_ref: t.txn_ref }, money(t.amount_paise)); if (r) { await refreshWallet().catch(() => {}); toast(r.status === 'SUCCESS' ? 'Payment sent.' : (r.message || 'Not completed.'), r.status === 'SUCCESS' ? 'good' : 'bad'); go('txn/' + t.txn_ref); } });
  const cat = $('#cat', host);
  if (cat) cat.addEventListener('click', () => openSheet(html`<h2>Change category</h2><p class="muted small">Correct it once and the AI remembers.</p><ul class="list" style="margin-top:12px;box-shadow:none;background:var(--surface-2)">${CATEGORIES.map((c) => html`<li><button class="row" data-cat="${c}" style="grid-template-columns:minmax(0,1fr) auto"><span class="t">${c}</span>${c === t.category ? icon('check') : ''}</button></li>`)}</ul>`,
    { label: 'Change category', onMount: (b, h) => b.addEventListener('click', async (e) => {
      const r = e.target.closest('[data-cat]'); if (!r) return;
      try { await api(`/transactions/${t.txn_ref}/category`, { method: 'PATCH', body: { category: r.dataset.cat } }); h.close(); toast('Thanks, the AI will remember that.', 'good'); go('txn/' + t.txn_ref); }
      catch (ex) { toast(errText(ex), 'bad'); }
    }) }));
}
