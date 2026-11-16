import { state, refreshWallet } from '../state.js';
import { html, paint, $, $$, money, rupees } from '../ui.js';
import { icon } from '../icons.js';
import { keypadHtml, bindAmount } from '../keypad.js';
import { reviewPayment } from '../flow.js';
import { showDone } from '../done.js';

export async function mount(host, ctx) {
  const kind = ctx.name === 'add' ? 'TOPUP' : 'WITHDRAW';
  await refreshWallet().catch(() => {});
  const w = state.wallet;
  const add = kind === 'TOPUP';
  paint(host, html`
    <div class="pay-screen">
      <div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>${add ? 'Add money' : 'Withdraw'}</h1></div>
      <div class="grow-body">
        <div class="payee"><span class="av" style="--s:64px;--av-bg:var(--brand-tint);--av-fg:var(--brand)">${icon(add ? 'add' : 'withdraw')}</span><b>${add ? 'From your bank (UPI)' : 'To your bank account'}</b><span class="muted small">${add ? `Wallet can hold up to ${rupees(w.max_balance_paise)}` : 'OTP needed from ' + rupees(w.otp_threshold_paise)}</span></div>
        <div class="amt-display" id="amt" role="status"></div>
        <div class="quick">${[500, 1000, 2000, 5000].map((n) => html`<button class="chip" type="button" data-q="${n}">${rupees(n * 100)}</button>`)}</div>
        <div class="hintline" id="hint" aria-live="polite"></div>
      </div>
      <div class="pay-foot">${keypadHtml()}<div class="from">Balance ${money(w.balance_paise)}</div><button class="btn block" id="go" disabled>${add ? 'Add money' : 'Withdraw'}</button></div>
    </div>`);
  const goBtn = $('#go', host), hint = $('#hint', host);
  const pad = bindAmount(host, { onChange: (v) => {
    const n = parseFloat(v), paise = Math.round(n * 100);
    let problem = '';
    if (n > 0) {
      if (add && paise > 5_000_000) problem = 'You can add up to ₹50,000 at a time.';
      else if (add && w.balance_paise + paise > w.max_balance_paise) problem = `That would take the wallet over ${rupees(w.max_balance_paise)}.`;
      else if (!add && paise > w.balance_paise) problem = `That is more than your balance of ${money(w.balance_paise)}.`;
    }
    hint.className = 'hintline ' + (problem ? 'bad' : ''); hint.textContent = problem;
    goBtn.disabled = !(n > 0) || !!problem;
    goBtn.textContent = n > 0 ? `${add ? 'Add' : 'Withdraw'} ${money(paise)}` : (add ? 'Add money' : 'Withdraw');
  } });
  $$('[data-q]', host).forEach((b) => b.addEventListener('click', () => pad.set(b.dataset.q)));
  goBtn.addEventListener('click', async () => {
    const res = await reviewPayment({ kind, amount: pad.value });
    if (!res) return;
    await refreshWallet().catch(() => {});
    showDone(host, res, { title: add ? 'Added to your wallet' : 'Sent to your bank', sub: add ? 'From your bank (UPI)' : 'To your bank account', who: 'Your bank' });
  });
  return () => pad.dispose();
}
