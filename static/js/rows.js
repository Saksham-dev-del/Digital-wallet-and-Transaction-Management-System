// Shared transaction row for Home and Activity.
import { html, money, avatar, timeShort } from './ui.js';
import { icon } from './icons.js';

export const statusTag = (t) => ({
  PENDING_OTP: html`<span class="tag warn">Awaiting OTP</span>`, BLOCKED: html`<span class="tag bad">Held for review</span>`,
  FAILED: html`<span class="tag bad">Failed</span>`, PENDING: html`<span class="tag">Processing</span>` }[t.status] || '');

export function txnRow(t) {
  const out = t.direction === 'DEBIT';
  const who = t.counterparty ? t.counterparty.name : (t.type === 'TOPUP' ? 'Added to wallet' : 'Withdrawn to bank');
  const lead = t.counterparty ? avatar(who) : html`<span class="lead">${icon(t.type === 'TOPUP' ? 'add' : 'withdraw')}</span>`;
  const bits = [];
  if (t.type === 'TRANSFER') bits.push(out ? t.category : 'Received');
  if (t.note && t.counterparty) bits.push(t.note);
  const right = t.status === 'SUCCESS'
    ? html`<div class="amt ${out ? '' : 'in'}">${out ? '−' : '+'}${money(t.amount_paise)}<small>${timeShort(t.created_at)}</small></div>`
    : html`<div class="amt">${money(t.amount_paise)}<small>${statusTag(t)}</small></div>`;
  return html`<li><button class="row" data-ref="${t.txn_ref}">${lead}<div style="min-width:0"><div class="t">${who}</div><div class="s">${bits.join(' · ')}</div></div>${right}</button></li>`;
}
