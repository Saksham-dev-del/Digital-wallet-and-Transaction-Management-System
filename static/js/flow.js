// The payment flow shared by Pay, Add money and Withdraw:
//   review sheet (AI shield scan) -> confirm -> optional OTP step -> final result.
import { api } from './api.js';
import { emitTrace } from './state.js';
import { html, raw, money, esc, errText, uuid, sleep, $, $$ } from './ui.js';
import { icon } from './icons.js';
import { openSheet } from './sheet.js';

const CHECKS = [
  { label: 'Payment size', codes: ['drain', 'half_balance', 'unusual_size', 'round'] },
  { label: 'Recipient', codes: ['new_recipient', 'new_account'], transferOnly: true },
  { label: 'Speed of payments', codes: ['velocity', 'structuring', 'otp_failures'] },
  { label: 'Time of day', codes: ['night'] },
  { label: 'Daily limit', codes: ['daily_limit'] },
  { label: 'Your usual pattern (AI model)', codes: ['ai_anomaly'] },
];

export const shield = (st) => raw(`<div class="shield" data-state="${st}"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle class="ring" cx="24" cy="24" r="21" pathLength="100"/><path d="M24 9.5 14 13.4v7.6c0 6.3 4.1 10.8 10 13.2 5.9-2.4 10-6.9 10-13.2v-7.6z" stroke-width="2.4"/><path class="tick" d="m19 22.6 3.6 3.6 6.6-7" pathLength="30"/><path class="bang" d="M24 17.5v6.3M24 28.2v.01"/></svg></div>`);

const ENDPOINT = { TRANSFER: '/wallet/transfer', TOPUP: '/wallet/topup', WITHDRAW: '/wallet/withdraw' };

function checkRows(kind) {
  return CHECKS.filter((c) => !(c.transferOnly && kind !== 'TRANSFER'));
}

/** Opens the review sheet. Resolves with the final payment result (SUCCESS / BLOCKED / FAILED) or null if cancelled. */
export function reviewPayment({ kind, recipient, amount, note = '', category = '' }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (v) => { if (!settled) { settled = true; resolve(v); } };
    const key = uuid();
    const paise = Math.round(parseFloat(amount) * 100);
    const checks = kind === 'TOPUP' ? [] : checkRows(kind);
    const toName = kind === 'TRANSFER' ? recipient.name : kind === 'WITHDRAW' ? 'Your bank account' : 'Your wallet';
    const verb = kind === 'TOPUP' ? 'Add' : kind === 'WITHDRAW' ? 'Withdraw' : 'Pay';

    const initial = html`
      <div class="center">${kind === 'TOPUP' ? '' : shield('scan')}
        <h2 id="rv-title">${kind === 'TOPUP' ? 'Add money to your wallet' : 'Checking this payment'}</h2>
        <p class="muted small" id="rv-sub">${kind === 'TOPUP' ? 'The money comes from your own bank, so no risk check is needed.' : 'The AI shield looks at size, recipient, timing and your usual pattern.'}</p></div>
      <ul class="checks" id="rv-checks">${checks.map((c, i) => html`<li data-s="pending" style="animation-delay:${i * 90}ms"><span class="spinner"></span>${c.label}</li>`)}</ul>
      <div id="rv-reasons"></div>
      <dl class="kv">
        <dt>${kind === 'TRANSFER' ? 'To' : kind === 'WITHDRAW' ? 'To' : 'Into'}</dt><dd>${toName}${kind === 'TRANSFER' ? html`<br><small class="muted mono">${recipient.wallet_code}</small>` : ''}</dd>
        <dt>Amount</dt><dd>${money(paise)}</dd>
        ${kind === 'TRANSFER' ? html`<dt>Category</dt><dd id="rv-cat">${category || '…'}</dd>` : ''}
        ${kind !== 'TOPUP' ? html`<dt>Balance after</dt><dd id="rv-after">…</dd>` : ''}
      </dl>
      <div id="rv-err" class="err" role="alert"></div>
      <div class="actions"><button class="btn block" id="rv-pay" disabled>${verb} ${money(paise)}</button><button class="btn ghost block" data-close>Cancel</button></div>`;

    const handle = openSheet(initial, { label: 'Review payment', onClose: () => finish(null), onMount: (body, h) => start(body, h) });

    async function start(body, h) {
      const payBtn = $('#rv-pay', body), err = $('#rv-err', body);
      let preview = null;
      if (kind !== 'TOPUP') {
        try {
          const wait = sleep(1150);
          const req = api('/wallet/transfer/preview', { method: 'POST', body: { to: recipient && recipient.wallet_code, amount: String(amount), note, kind: kind === 'WITHDRAW' ? 'WITHDRAW' : 'TRANSFER' } });
          [preview] = await Promise.all([req, wait]);
        } catch (e) { err.textContent = errText(e); $('.shield', body)?.setAttribute('data-state', 'bad'); return; }
        await reveal(body, preview);
      } else { payBtn.disabled = false; }
      if (payBtn.textContent && preview && preview.outcome === 'BLOCKED') payBtn.textContent = 'Send for review';
      payBtn.addEventListener('click', async () => {
        payBtn.disabled = true; err.textContent = '';
        try {
          const cat = category || (preview && preview.category.category) || undefined;
          const bodyJson = kind === 'TRANSFER' ? { to: recipient.wallet_code, amount: String(amount), note, ...(cat ? { category: cat } : {}) } : { amount: String(amount) };
          let res = await api(ENDPOINT[kind], { method: 'POST', body: bodyJson, headers: { 'Idempotency-Key': key } });
          if (res.trace) emitTrace(res.trace, `${verb} ${money(paise)}`);
          if (res.status === 'PENDING_OTP') {
            res = await runOtp(h, res, `${money(paise)} to ${toName}`);
            if (!res) return;
          }
          if (res.status === 'FAILED') { err.textContent = res.message || 'The payment could not be completed.'; return; }
          finish(res); h.close();
        } catch (e) { err.textContent = errText(e); payBtn.disabled = false; }
      });
    }

    async function reveal(body, p) {
      const flagged = new Set(p.risk.reasons.map((r) => r.code));
      const lis = $$('#rv-checks li', body);
      for (let i = 0; i < lis.length; i++) {
        await sleep(110);
        const hit = checks[i].codes.some((c) => flagged.has(c));
        lis[i].dataset.s = hit ? 'flag' : 'ok';
        lis[i].innerHTML = `${icon(hit ? 'alert' : 'check').s}${esc(checks[i].label)}`;
      }
      const st = p.outcome === 'INSTANT' ? 'ok' : p.outcome === 'OTP' ? 'warn' : 'bad';
      const title = { INSTANT: 'Cleared by the AI shield', OTP: 'Extra verification needed', BLOCKED: 'This payment looks risky' }[p.outcome];
      const sub = { INSTANT: `Risk ${p.risk.score}/100. It goes through instantly.`,
        OTP: p.risk.level === 'LOW' ? 'Payments of ₹5,000 or more always need an OTP.' : `Risk ${p.risk.score}/100. We will ask for an OTP first.`,
        BLOCKED: `Risk ${p.risk.score}/100. It will be held for review and no money moves.` }[p.outcome];
      $('.shield', body).dataset.state = st;
      $('#rv-title', body).textContent = title;
      $('#rv-sub', body).textContent = sub;
      const reasons = p.risk.reasons.filter((r) => r.code !== 'ai_anomaly' || p.risk.reasons.length === 1);
      if (reasons.length) $('#rv-reasons', body).innerHTML = `<ul class="reasons">${reasons.map((r) => `<li>${esc(r.text)}</li>`).join('')}</ul>`;
      if ($('#rv-cat', body)) $('#rv-cat', body).textContent = category || p.category.category;
      $('#rv-after', body).textContent = money(p.balance_after_paise);
      if (p.balance_after_paise < 0) { $('#rv-err', body).textContent = 'This is more than your balance.'; return; }
      $('#rv-pay', body).disabled = false;
    }
  });
}

/** Replaces the sheet content with the OTP step. Resolves with the final result, or null once the sheet is closed. */
export function runOtp(handle, pending, summary) {
  return new Promise((resolve) => {
    const content = html`
      <h2 id="otp-title">Enter the OTP</h2>
      <p class="muted">We sent a 6-digit code to your phone to confirm ${summary}.</p>
      <div class="otp-boxes" id="otp-boxes" role="group" aria-label="6 digit code">${[0, 1, 2, 3, 4, 5].map((i) => html`<input inputmode="numeric" maxlength="1" autocomplete="${i === 0 ? 'one-time-code' : 'off'}" aria-label="Digit ${i + 1}">`)}</div>
      <div id="otp-err" class="err" role="alert"></div>
      <p class="small muted" id="otp-timer"></p>
      ${pending.demo_otp ? html`<div class="demo-note">Demo mode: your code is <b>${pending.demo_otp}</b>. It is also printed in the server console.</div>` : ''}
      <div class="actions"><button class="btn block" id="otp-go" disabled>Verify and pay</button><button class="btn ghost block" data-close>Cancel</button></div>`;
    handle.setContent(content, (body) => {
      const boxes = $$('#otp-boxes input', body), err = $('#otp-err', body), go = $('#otp-go', body), timer = $('#otp-timer', body);
      let done = false;
      const code = () => boxes.map((b) => b.value).join('');
      boxes.forEach((b, i) => {
        b.addEventListener('input', () => {
          b.value = b.value.replace(/\D/g, '').slice(-1);
          if (b.value && i < 5) boxes[i + 1].focus();
          go.disabled = code().length !== 6;
          if (code().length === 6) setTimeout(() => go.click(), 120);
        });
        b.addEventListener('keydown', (e) => { if (e.key === 'Backspace' && !b.value && i > 0) boxes[i - 1].focus(); });
        b.addEventListener('paste', (e) => {
          const t = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
          if (!t) return;
          e.preventDefault();
          t.split('').forEach((d, k) => { boxes[k].value = d; });
          go.disabled = t.length !== 6;
          boxes[Math.min(t.length, 5)].focus();
          if (t.length === 6) setTimeout(() => go.click(), 120);
        });
      });
      const expires = pending.otp_expires_at ? new Date(pending.otp_expires_at).getTime() : Date.now() + 300000;
      const tick = () => {
        const left = Math.max(0, Math.round((expires - Date.now()) / 1000));
        timer.textContent = left ? `Code valid for ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : 'This code has expired. Close and start again.';
        if (!left) go.disabled = true;
      };
      tick();
      const clock = setInterval(() => { if (done || !document.contains(body)) clearInterval(clock); else tick(); }, 1000);
      go.addEventListener('click', async () => {
        if (code().length !== 6 || done) return;
        go.disabled = true; err.textContent = '';
        try {
          const res = await api('/wallet/transfer/confirm', { method: 'POST', body: { txn_ref: pending.txn_ref, otp: code() } });
          if (res.trace) emitTrace(res.trace, 'OTP confirmed');
          done = true; resolve(res);
        } catch (e) {
          err.textContent = errText(e);
          const row = $('#otp-boxes', body);
          if (['otp_locked', 'otp_expired', 'not_pending'].includes(e.code)) { done = true; setTimeout(() => resolve({ status: 'FAILED', message: errText(e) }), 1400); return; }
          row.classList.remove('shake'); void row.offsetWidth; row.classList.add('shake');
          boxes.forEach((x) => { x.value = ''; }); boxes[0].focus(); go.disabled = true;
        }
      });
    });
  });
}

/** Standalone OTP sheet for a payment that is already waiting (Home banner, Activity list). */
export function enterOtp(pending, summary) {
  return new Promise((resolve) => {
    let finished = false;
    const finish = (v) => { if (!finished) { finished = true; resolve(v); } };
    const h = openSheet(html``, { label: 'Enter OTP', onClose: () => finish(null) });
    runOtp(h, pending, summary).then((r) => { finish(r); h.close(); });
  });
}
