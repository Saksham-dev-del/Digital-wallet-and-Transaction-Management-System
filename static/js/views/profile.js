import { api } from '../api.js';
import { state, go, refreshWallet } from '../state.js';
import { html, paint, $, $$, money, rupees, avatar, prefs, applyTheme, toast, copyText } from '../ui.js';
import { icon } from '../icons.js';
import { openSheet } from '../sheet.js';
import { openReceive } from './receive.js';
import { openHoodSheet } from '../hood.js';

export async function mount(host) {
  const w = await refreshWallet().catch(() => state.wallet);
  const u = state.user, isAdmin = u.role === 'admin';
  const item = (id, ic, title, sub, right) => html`<button class="row" data-act="${id}"><span class="lead">${icon(ic)}</span><div style="min-width:0"><div class="t">${title}</div><div class="s">${sub}</div></div>${right || icon('chevR')}</button>`;
  const themePref = prefs.get('theme', 'system'), hidden = prefs.get('hide', '0') === '1';
  paint(host, html`
    <div class="view">
      <div class="profile-top">${avatar(u.full_name, { size: 76 })}<h1>${u.full_name}</h1><p class="muted">${u.email}</p></div>
      <div class="group">
        ${item('copy', 'copy', 'Wallet ID', w.wallet_code, html`<span class="tag brand">Copy</span>`)}
        ${item('qr', 'qr', 'My QR code', 'Let people pay you')}
        ${item('limits', 'shield', 'Limits and safety', `Daily ${rupees(w.daily_limit_paise)} · OTP from ${rupees(w.otp_threshold_paise)}`)}
        ${item('scheduled', 'clock', 'Scheduled payments', 'Rent, subscriptions, pocket money')}
      </div>
      <div class="group">
        <div class="row"><span class="lead">${icon('sun')}</span><div class="t">Appearance</div><div class="seg" id="theme" role="group" aria-label="Appearance">${['system', 'light', 'dark'].map((t) => html`<button data-pref="${t}" aria-pressed="${String(t === themePref)}">${t[0].toUpperCase() + t.slice(1)}</button>`)}</div></div>
        <div class="row"><span class="lead">${icon('eye')}</span><div style="min-width:0"><div class="t">Hide balance</div><div class="s">On the home screen</div></div><button class="switch" id="hide" role="switch" aria-checked="${String(hidden)}" aria-label="Hide balance"></button></div>
      </div>
      <div class="group">
        ${item('hood', 'cpu', 'Under the hood', 'Live locks, transactions and the audit log')}
        ${item('lab', 'cpu', 'Lab console', 'Deadlocks, CPU scheduling, memory, files')}
        ${isAdmin ? item('admin', 'shield', 'Admin console', 'Held payments, accounts and the books') : ''}
      </div>
      <button class="btn danger block" id="signout" style="margin-top:22px">${icon('logout')} Sign out</button>
      <p class="hint center" style="margin-top:14px">Smart Wallet · a DBMS + OS + AI project</p>
    </div>`);
  host.addEventListener('click', async (e) => {
    const a = e.target.closest('[data-act]');
    if (a) {
      const id = a.dataset.act;
      if (id === 'copy') toast((await copyText(w.wallet_code)) ? 'Wallet ID copied.' : 'Could not copy.', 'good');
      else if (id === 'qr') openReceive();
      else if (id === 'hood') openHoodSheet();
      else if (id === 'lab') go('lab/overview');
      else if (id === 'limits') openSheet(html`<h2>Limits and safety</h2><dl class="kv"><dt>Daily limit</dt><dd>${money(w.daily_limit_paise)}</dd><dt>Used in 24 hours</dt><dd>${money(w.spent_24h_paise)}</dd><dt>OTP needed from</dt><dd>${money(w.otp_threshold_paise)}</dd><dt>Wallet can hold</dt><dd>${money(w.max_balance_paise)}</dd></dl><p class="hint" style="margin-top:12px">The AI shield can also ask for an OTP on smaller payments that look unusual.</p><div class="actions"><button class="btn ghost block" data-close>Close</button></div>`, { label: 'Limits and safety' });
      else go(id);
      return;
    }
    const th = e.target.closest('[data-pref]');
    if (th) { prefs.set('theme', th.dataset.pref); applyTheme(); $$('#theme button', host).forEach((b) => b.setAttribute('aria-pressed', String(b === th))); return; }
    if (e.target.closest('#hide')) { const sw = $('#hide', host), on = sw.getAttribute('aria-checked') !== 'true'; sw.setAttribute('aria-checked', String(on)); prefs.set('hide', on ? '1' : '0'); return; }
    if (e.target.closest('#signout')) window.dispatchEvent(new Event('sw:signout'));
  });
}
