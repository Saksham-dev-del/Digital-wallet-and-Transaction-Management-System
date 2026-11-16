import { api } from '../api.js';
import { html, paint, $, money, dateTime, avatar, toast, busy, errText } from '../ui.js';
import { icon } from '../icons.js';
import { openSheet } from '../sheet.js';

const FREQ = { ONCE: 'Once', DAILY: 'Every day', WEEKLY: 'Every week', MONTHLY: 'Every month' };
const TAG = { ACTIVE: 'brand', RUNNING: 'warn', DONE: 'ok', FAILED: 'bad', CANCELLED: '' };

export async function mount(host) {
  paint(host, html`
    <div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Scheduled</h1><button class="icon-btn" id="new" aria-label="New scheduled payment">${icon('add')}</button></div>
    <div class="view"><p class="muted small">Due payments wait in a priority queue and worker threads run them (priority 1 first). Payments of ₹5,000 or more can't be automated because they need an OTP.</p><div id="list" style="margin-top:14px"><div class="skel"></div></div></div>`);

  async function load() {
    try {
      const { scheduled } = await api('/scheduled');
      paint($('#list', host), scheduled.length ? html`<ul class="list">${scheduled.map((s) => html`<li><div class="row">${avatar(s.to_name)}<div style="min-width:0"><div class="t">${s.to_name}</div><div class="s">${FREQ[s.frequency]} · ${dateTime(s.next_run_at)}</div></div><div class="amt">${money(s.amount_paise)}<small><span class="tag ${TAG[s.status] || ''}">${s.status.toLowerCase()}</span></small></div></div>
        <div style="padding:0 14px 12px;display:flex;justify-content:space-between;gap:10px;align-items:center"><span class="s small">${s.note ? s.note + ' · ' : ''}priority ${s.priority}${s.last_result ? ' · ' + s.last_result : ''}</span>${s.status === 'ACTIVE' ? html`<button class="link-btn" data-cancel="${s.sched_id}">Cancel</button>` : ''}</div></li>`)}</ul>`
        : html`<div class="empty"><h3>Nothing scheduled</h3><p>Schedule rent or pocket money once and forget about it.</p><button class="btn" id="new2">Schedule a payment</button></div>`);
    } catch (e) { paint($('#list', host), html`<p class="err">${errText(e)}</p>`); }
  }

  function openForm() {
    openSheet(html`
      <h2>Schedule a payment</h2>
      <form id="sf" novalidate style="margin-top:12px">
        <div class="field"><label for="s-to">Pay to</label><input id="s-to" placeholder="Wallet ID, e.g. neha@swallet" autocomplete="off"></div>
        <div class="field"><label for="s-amt">Amount in rupees</label><input id="s-amt" inputmode="decimal" placeholder="500" autocomplete="off"></div>
        <div class="field"><label for="s-note">Note</label><input id="s-note" maxlength="80" placeholder="e.g. mess fees"></div>
        <div class="field"><label for="s-when">When</label><select id="s-when"><option value="60">In 1 minute (demo)</option><option value="300">In 5 minutes</option><option value="tomorrow">Tomorrow at 9:00 am</option><option value="custom">Pick date and time</option></select></div>
        <div class="field hidden" id="custom-box"><input id="s-custom" type="datetime-local" aria-label="Date and time"></div>
        <div class="field"><label for="s-freq">Repeats</label><select id="s-freq">${Object.entries(FREQ).map(([k, v]) => html`<option value="${k}">${v}</option>`)}</select></div>
        <div class="field"><label for="s-pri">Priority</label><select id="s-pri"><option value="1">1 - most urgent</option><option value="3">3 - high</option><option value="5" selected>5 - normal</option><option value="7">7 - low</option><option value="9">9 - lowest</option></select></div>
        <div id="s-err" class="err" role="alert"></div>
        <div class="actions"><button class="btn block" type="submit">Schedule</button><button class="btn ghost block" type="button" data-close>Cancel</button></div>
      </form>`, { label: 'Schedule a payment', onMount: (b, h) => {
      const when = $('#s-when', b);
      when.addEventListener('change', () => $('#custom-box', b).classList.toggle('hidden', when.value !== 'custom'));
      $('#sf', b).addEventListener('submit', async (e) => {
        e.preventDefault();
        const err = $('#s-err', b); err.textContent = '';
        const body = { to: $('#s-to', b).value.trim(), amount: $('#s-amt', b).value.replace(/,/g, '').trim(), note: $('#s-note', b).value.trim(), frequency: $('#s-freq', b).value, priority: Number($('#s-pri', b).value) };
        if (!body.to || !(parseFloat(body.amount) > 0)) { err.textContent = 'Enter who to pay and an amount above zero.'; return; }
        if (when.value === 'custom') { const v = $('#s-custom', b).value; if (!v) { err.textContent = 'Pick a date and time.'; return; } body.run_at = new Date(v).toISOString(); }
        else if (when.value === 'tomorrow') { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); body.run_at = d.toISOString(); }
        else body.in_seconds = Number(when.value);
        await busy($('button[type=submit]', b), async () => {
          try { await api('/scheduled', { method: 'POST', body }); h.close(); toast('Payment scheduled.', 'good'); await load(); } catch (ex) { err.textContent = errText(ex); }
        });
      });
    } });
  }

  host.addEventListener('click', async (e) => {
    if (e.target.closest('#new') || e.target.closest('#new2')) { openForm(); return; }
    const c = e.target.closest('[data-cancel]');
    if (c) await busy(c, async () => { try { await api('/scheduled/' + c.dataset.cancel, { method: 'DELETE' }); toast('Cancelled.'); await load(); } catch (ex) { toast(errText(ex), 'bad'); } });
  });
  await load();
  const timer = setInterval(load, 4000);       // keep the list fresh so you can watch a payment run
  return () => clearInterval(timer);
}
