// Full-screen result of a payment: success tick, receipt summary and "what happened inside".
import { state, go, emitTrace } from './state.js';
import { html, paint, $, money, dateTime, copyText, toast, avatar } from './ui.js';
import { icon } from './icons.js';
import { traceHtml } from './trace.js';

const tick = (cls = '') => html`<svg class="tickmark ${cls}" viewBox="0 0 104 104" aria-hidden="true"><circle cx="52" cy="52" r="48"/><path d="m32 54 14 14 27-30"/></svg>`;

export function showDone(host, res, { title, sub, who }) {
  if (res.trace) emitTrace(res.trace, title);
  const held = res.status === 'BLOCKED';
  paint(host, html`
    <div class="done">
      <div class="grow-body">
        ${held ? html`<svg class="tickmark warn" viewBox="0 0 104 104" aria-hidden="true"><circle cx="52" cy="52" r="48"/><path d="M52 30v28M52 72v.1"/></svg>` : tick()}
        <h1>${held ? 'Held for review' : money(res.amount_paise)}</h1>
        <p class="sub">${held ? 'This payment looks risky, so no money moved.' : title}</p>
        ${held ? '' : html`<p class="sub">${sub}</p>`}
        <div class="receipt-card"><dl class="kv">
          ${who ? html`<dt>With</dt><dd>${who}</dd>` : ''}
          <dt>Reference</dt><dd class="mono"><button class="link-btn mono" id="copy-ref" aria-label="Copy reference">${res.txn_ref} ${icon('copy', 'inline-ic')}</button></dd>
          <dt>When</dt><dd>${dateTime(res.created_at)}</dd>
          ${held ? '' : html`<dt>Balance now</dt><dd class="num">${money(res.balance_paise)}</dd>`}
        </dl></div>
        ${held && res.risk ? html`<ul class="reasons" style="width:100%;text-align:left;margin-top:14px">${res.risk.reasons.slice(0, 4).map((r) => html`<li>${r.text}</li>`)}</ul>` : ''}
        ${res.trace ? html`<details><summary>What happened inside</summary>${traceHtml(res.trace)}<p class="hint" style="padding:8px 0 12px">The same steps stream live into the "Under the hood" panel.</p></details>` : ''}
      </div>
      <div class="btns"><button class="btn block" id="done-ok">Done</button><button class="btn ghost block" id="done-rcpt">${held ? 'See in activity' : 'View receipt'}</button></div>
    </div>`);
  $('#done-ok', host).addEventListener('click', () => go('home'));
  $('#done-rcpt', host).addEventListener('click', () => go(`txn/${res.txn_ref}`));
  $('#copy-ref', host).addEventListener('click', async () => toast((await copyText(res.txn_ref)) ? 'Reference copied.' : 'Could not copy.'));
  $('#done-ok', host).focus();
}
