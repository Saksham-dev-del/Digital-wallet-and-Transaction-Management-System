import { api, downloadFile } from '../api.js';
import { state, go } from '../state.js';
import { html, paint, $, $$, money, rupees, moneyParts, avatar, prefs, toast, errText, reducedMotion } from '../ui.js';
import { icon, logo } from '../icons.js';
import { txnRow } from '../rows.js';
import { enterOtp } from '../flow.js';
import { openReceive } from './receive.js';
import { openHoodSheet } from '../hood.js';

const greeting = () => { const h = new Date().getHours(); return h < 5 ? 'Still up' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : h < 22 ? 'Good evening' : 'Good night'; };

export async function mount(host) {
  paint(host, html`<div class="view"><div class="hello"><div class="who"><p>${greeting()}</p><h1>${state.user.full_name.split(' ')[0]}</h1></div></div><div class="skel" style="height:204px;border-radius:28px"></div><div class="skel"></div><div class="skel"></div></div>`);
  let w, tx, ppl;
  try { [w, tx, ppl] = await Promise.all([api('/wallet'), api('/transactions?limit=6'), api('/recipients/recent')]); }
  catch (e) { paint(host, html`<div class="view"><div class="empty"><h3>Couldn't load your wallet</h3><p>${errText(e)}</p><button class="btn" data-go="home">Try again</button></div></div>`); return; }
  state.wallet = w;
  let hidden = prefs.get('hide', '0') === '1';
  const used = Math.min(100, (w.spent_24h_paise / w.daily_limit_paise) * 100);
  const pending = tx.transactions.find((t) => t.status === 'PENDING_OTP');
  const person = (c) => html`<button class="person" data-to="${c.wallet_code}" aria-label="Pay ${c.name}">${avatar(c.name, { size: 54, merchant: c.merchant })}<span>${c.name.split(' ')[0]}</span></button>`;
  const act = (id, ic, label) => html`<button class="act" data-act="${id}"><span class="ic">${icon(ic)}</span>${label}</button>`;

  paint(host, html`
    <div class="view">
      <header class="hello">
        <button class="icon-btn plain" data-go="profile" aria-label="Profile" style="padding:0;width:auto;height:auto">${avatar(state.user.full_name, { size: 46 })}</button>
        <div class="who"><p>${greeting()}</p><h1>${state.user.full_name.split(' ')[0]}</h1></div>
        <button class="icon-btn" data-go="ask" aria-label="Ask AI">${icon('sparkle')}</button>
      </header>
      <div class="wcard" id="wcard">
        <div class="top"><span class="wmark">${logo()}Smart Wallet</span><span class="chip-ic" aria-hidden="true"></span></div>
        <div><div class="label">Wallet balance <button class="eye" id="eye" aria-label="Hide balance">${icon('eye')}</button></div><div class="bal" id="bal"></div></div>
        <div class="foot"><span class="id">${w.wallet_code}</span>
          <div class="limit">Today ${rupees(w.spent_24h_paise)} of ${rupees(w.daily_limit_paise)}<div class="track"><i style="width:${used.toFixed(1)}%"></i></div></div></div>
      </div>
      <div class="acts">${act('pay', 'send', 'Pay')}${act('receive', 'qr', 'Receive')}${act('add', 'add', 'Add money')}${act('withdraw', 'withdraw', 'Withdraw')}
        ${act('scheduled', 'clock', 'Schedule')}${act('ask', 'sparkle', 'Ask AI')}${act('statement', 'download', 'Statement')}${act('hood', 'cpu', 'Under the hood')}</div>
      ${pending ? html`<button class="banner" id="otp-banner">${icon('hourglass')}<span class="grow">Payment waiting for OTP<small>${money(pending.amount_paise)} to ${pending.counterparty ? pending.counterparty.name : 'your bank'}. Tap to enter the code.</small></span>${icon('chevR')}</button>` : ''}
      <div class="section-h"><h2>People</h2></div>
      <div class="people"><button class="person" data-go="pay" aria-label="Pay someone new"><span class="plus">${icon('add')}</span><span>New</span></button>${ppl.contacts.filter((c) => !c.merchant).slice(0, 9).map(person)}</div>
      <div id="ainote"></div>
      <div class="section-h"><h2>Recent</h2><button class="link-btn" data-go="activity">See all</button></div>
      ${tx.transactions.length ? html`<ul class="list" id="recent">${tx.transactions.slice(0, 5).map(txnRow)}</ul>` : html`<div class="empty"><h3>No payments yet</h3><p>Add some money and make your first payment.</p><button class="btn" data-go="add">Add money</button></div>`}
    </div>`);

  const bal = $('#bal', host), eye = $('#eye', host);
  const drawBal = () => {
    const p = moneyParts(w.balance_paise);
    bal.innerHTML = hidden ? '<span class="cur">₹</span>••••••' : `<span class="cur">₹</span>${p.whole}<span class="paise">.${p.frac}</span>`;
    eye.innerHTML = icon(hidden ? 'eyeOff' : 'eye').s;
    eye.setAttribute('aria-label', hidden ? 'Show balance' : 'Hide balance');
  };
  drawBal();
  eye.addEventListener('click', () => { hidden = !hidden; prefs.set('hide', hidden ? '1' : '0'); drawBal(); });

  const card = $('#wcard', host);
  if (window.matchMedia('(hover: hover)').matches && !reducedMotion()) {
    card.addEventListener('pointermove', (e) => { const r = card.getBoundingClientRect(); card.style.setProperty('--ry', ((e.clientX - r.left) / r.width - .5) * 8 + 'deg'); card.style.setProperty('--rx', (-((e.clientY - r.top) / r.height - .5)) * 8 + 'deg'); });
    card.addEventListener('pointerleave', () => { card.style.setProperty('--rx', '0deg'); card.style.setProperty('--ry', '0deg'); });
  }

  host.addEventListener('click', async (e) => {
    const to = e.target.closest('[data-to]'); if (to) { go('pay/' + encodeURIComponent(to.dataset.to)); return; }
    const ref = e.target.closest('[data-ref]'); if (ref) { go('txn/' + ref.dataset.ref); return; }
    if (e.target.closest('#otp-banner')) { const res = await enterOtp({ txn_ref: pending.txn_ref }, money(pending.amount_paise)); if (res) { toast(res.status === 'SUCCESS' ? 'Payment sent.' : (res.message || 'Not completed.'), res.status === 'SUCCESS' ? 'good' : 'bad'); go('home'); } return; }
    const a = e.target.closest('[data-act]'); if (!a) return;
    const id = a.dataset.act;
    if (id === 'receive') openReceive();
    else if (id === 'hood') openHoodSheet();
    else if (id === 'statement') { try { await downloadFile('/transactions/export.csv', 'wallet-statement.csv'); toast('Statement downloaded.', 'good'); } catch (ex) { toast(errText(ex), 'bad'); } }
    else go(id);
  });

  api('/ai/insights').then((ins) => {
    const tip = ins.tips && ins.tips[0];
    if (!tip || !document.contains($('#ainote', host))) return;
    paint($('#ainote', host), html`<button class="ainote" data-go="insights"><span class="spark">${icon('sparkle')}</span><span><p>${tip}</p><small>Health score ${ins.health.score}/100 · see all insights</small></span></button>`);
  }).catch(() => {});
}
