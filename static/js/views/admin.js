import { api } from '../api.js';
import { html, paint, $, $$, money, rupees, dateTime, toast, busy, errText } from '../ui.js';

export async function mount(el) {
  paint(el, html`<section class="page"><div class="page-head"><div><h1>Admin</h1><p>Review what the AI held back, look after accounts, and check the books.</p></div></div><div id="adm"><p class="muted">Loading…</p></div></section>`);
  const box = $('#adm', el);

  async function draw() {
    const [ov, al, us] = await Promise.all([api('/admin/overview'), api('/admin/alerts'), api('/admin/users')]);
    const sc = ov.status_counts;
    paint(box, html`
      <p style="font-size:16px;max-width:70ch"><b class="mono">${ov.users}</b> people and <b class="mono">${ov.merchants}</b> merchants hold <b class="mono">${money(ov.money_in_wallets_paise)}</b> in wallets.
        In the last 24 hours there were <b class="mono">${ov.txn_24h}</b> transactions and <b class="mono">${money(ov.volume_24h_paise)}</b> moved between wallets.
        Overall: ${Object.entries(sc).map(([k, v]) => `${v} ${k.replace('_', ' ').toLowerCase()}`).join(', ')}.</p>

      <div class="section"><h2>Payments held by the AI ${ov.open_alerts ? html`<span class="tag warn">${ov.open_alerts} open</span>` : ''}</h2>
        ${al.alerts.length ? html`<div class="scroll"><table class="tbl"><thead><tr><th>When</th><th>From</th><th>To</th><th class="num">Amount</th><th>Risk</th><th>Why the AI was worried</th><th></th></tr></thead><tbody>
          ${al.alerts.map((a) => html`<tr><td>${dateTime(a.created_at)}</td><td>${a.sender}<div class="small muted">${a.sender_email}</div></td><td>${a.recipient || ''}</td><td class="num mono">${money(a.amount_paise)}</td>
            <td class="mono">${a.risk_score}</td><td><ul class="reasons">${a.reasons.map((r) => html`<li>${r.text}</li>`)}</ul></td>
            <td>${a.review_status === 'OPEN' ? html`<div class="flex"><button class="btn small" data-act="approve" data-id="${a.alert_id}">Approve</button><button class="btn small danger" data-act="reject" data-id="${a.alert_id}">Reject</button></div>` : html`<span class="tag ${a.review_status === 'APPROVED' ? 'ok' : 'bad'}">${a.review_status.toLowerCase()}</span>`}</td></tr>`)}</tbody></table></div>`
          : html`<p class="muted">Nothing has been held yet. To see one, send a large payment that drains a wallet to a brand-new account.</p>`}</div>

      <div class="section"><h2>Accounts</h2><div class="scroll"><table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Wallet</th><th class="num">Balance</th><th>Status</th><th></th></tr></thead><tbody>
        ${us.users.map((u) => html`<tr><td>${u.full_name} ${u.role === 'admin' ? html`<span class="tag">admin</span>` : ''}</td><td class="small">${u.email}</td><td class="mono small">${u.wallet_code}</td><td class="num mono">${money(u.balance_paise)}</td>
          <td><span class="tag ${u.status === 'active' ? 'ok' : 'bad'}">${u.status}</span></td>
          <td>${u.role === 'admin' ? '' : html`<button class="btn small ghost" data-user="${u.user_id}" data-act="${u.status === 'active' ? 'freeze' : 'unfreeze'}">${u.status === 'active' ? 'Freeze' : 'Unfreeze'}</button>`}</td></tr>`)}</tbody></table></div></div>

      <div class="section"><h2>Books and models</h2>
        <div class="flex"><button class="btn" id="recon">Reconcile all wallets</button><button class="btn ghost" id="retrain">Retrain fraud model</button></div><div id="adm-out" style="margin-top:12px"></div></div>`);
  }

  box.addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.id) {
      if (!confirm(`${b.dataset.act === 'approve' ? 'Approve and send' : 'Reject'} this payment?`)) return;
      await busy(b, async () => { try { await api(`/admin/alerts/${b.dataset.id}/${b.dataset.act}`, { method: 'POST' }); toast('Done.', 'good'); await draw(); } catch (ex) { toast(errText(ex), 'bad'); } });
    } else if (b.dataset.user) {
      await busy(b, async () => { try { await api(`/admin/users/${b.dataset.user}/${b.dataset.act}`, { method: 'POST' }); await draw(); } catch (ex) { toast(errText(ex), 'bad'); } });
    } else if (b.id === 'recon') {
      await busy(b, async () => {
        try {
          const r = await api('/admin/reconcile');
          paint($('#adm-out', box), html`<p><span class="stamp ${r.mismatches.length ? 'bad' : 'good'}">${r.mismatches.length ? r.mismatches.length + ' mismatches' : 'Books balance'}</span> ${r.wallets_checked} wallets checked, database integrity: <b>${r.integrity_check}</b>.</p><p class="hint">${r.explanation}</p>`);
        } catch (ex) { toast(errText(ex), 'bad'); }
      });
    } else if (b.id === 'retrain') {
      await busy(b, async () => {
        try {
          const r = await api('/admin/ai/retrain', { method: 'POST' });
          paint($('#adm-out', box), html`<p><span class="stamp">Retrained</span> ${r.engine}: ${r.trained_on.synthetic} synthetic + ${r.trained_on.real} real payments.</p>`);
        } catch (ex) { toast(errText(ex), 'bad'); }
      });
    }
  });
  await draw();
}
