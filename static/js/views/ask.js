import { api } from '../api.js';
import { state, go } from '../state.js';
import { html, paint, $, money, errText } from '../ui.js';
import { icon } from '../icons.js';

const history = [];     // kept for the whole browser session
const SUGGEST = ["What's my balance?", 'Mera balance kitna hai?', 'How much did I spend on food this month?', 'Is mahine transport par kitna kharcha hua?',
  'Forecast for next week', 'Show my subscriptions', 'Why was my payment flagged?', 'Rohan ko 500 bhejo'];

export async function mount(host, ctx) {
  host.style.height = '100%';
  paint(host, html`
    <div class="chat-view">
      <div class="bar"><button class="icon-btn" data-back aria-label="Back">${icon('chevL')}</button><h1>Ask AI</h1><span class="tag brand" id="mode">${icon('sparkle')}</span></div>
      <div class="chat" id="chat" aria-live="polite"></div>
      <div class="suggest" id="chips">${SUGGEST.map((s) => html`<button type="button" class="chip" data-q="${s}">${s}</button>`)}</div>
      <div class="composer"><form id="ask"><input class="input" id="msg" autocomplete="off" maxlength="400" placeholder="Ask about your money, English or Hinglish" aria-label="Your question"><button class="btn" id="ask-go" aria-label="Send">${icon('send')}</button></form></div>
    </div>`);
  const chat = $('#chat', host), input = $('#msg', host);
  if (!history.length) history.push({ who: 'ai', text: `Hi ${state.user.full_name.split(' ')[0]}! Ask me about your balance, spending, forecast or subscriptions. I can also prepare a payment, but you always press Pay yourself.` });
  let pending = false;

  function draw() {
    paint(chat, html`${history.map((m, i) => html`<div class="msg ${m.who}">${m.text}${m.who === 'ai' && m.source ? html`<span class="src">${m.source === 'claude' ? 'Answered by Claude' : 'From your wallet data (offline rules)'}</span>` : ''}${m.action ? html`<div class="pay-card"><b>Pay ${m.action.to} ${m.action.amount ? money(Math.round(parseFloat(m.action.amount) * 100)) : ''}</b><button class="btn small" data-prefill="${i}">Review this payment</button></div>` : ''}</div>`)}${pending ? html`<div class="msg ai"><span class="typing"><i></i><i></i><i></i></span></div>` : ''}`);
    chat.scrollTop = chat.scrollHeight;
  }
  async function ask(text) {
    text = text.trim();
    if (!text || pending) return;
    pending = true; $('#ask-go', host).disabled = true;
    history.push({ who: 'me', text }); input.value = ''; draw();
    try {
      const r = await api('/ai/chat', { method: 'POST', body: { message: text } });
      history.push({ who: 'ai', text: r.reply, source: r.source, action: r.action && r.action.type === 'prefill_transfer' ? r.action : null });
    } catch (e) { history.push({ who: 'ai', text: errText(e) }); }
    pending = false; $('#ask-go', host).disabled = false; draw(); input.focus();
  }
  $('#ask', host).addEventListener('submit', (e) => { e.preventDefault(); ask(input.value); });
  $('#chips', host).addEventListener('click', (e) => { const b = e.target.closest('[data-q]'); if (b) ask(b.dataset.q); });
  chat.addEventListener('click', (e) => {
    const b = e.target.closest('[data-prefill]');
    if (!b) return;
    const a = history[Number(b.dataset.prefill)].action;
    if (String(a.to).includes('@')) go(`pay/${encodeURIComponent(a.to)}?amount=${encodeURIComponent(a.amount)}&note=${encodeURIComponent(a.note || '')}`);
    else go(`pay?q=${encodeURIComponent(a.to)}`);
  });
  draw();
  api('/ai/model').then((m) => { $('#mode', host).innerHTML = `${icon('sparkle').s}${m.assistant.model ? 'Claude' : 'Offline'}`; }).catch(() => {});
  if (ctx.query.get('q')) ask(ctx.query.get('q')); else input.focus({ preventScroll: true });
}
