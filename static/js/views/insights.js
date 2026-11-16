import { api } from '../api.js';
import { html, paint, $, money, rupees, dateShort, avatar, plural } from '../ui.js';
import { icon } from '../icons.js';
import { barChart, ring, meter } from '../charts.js';

const dshort = (d) => dateShort(d + 'T12:00:00');

export async function mount(host) {
  paint(host, html`<div class="bar"><h1>Insights</h1></div><div class="view"><div class="skel" style="height:250px;border-radius:30px"></div><div class="skel"></div></div>`);
  let ins;
  try { ins = await api('/ai/insights'); } catch (e) { paint(host, html`<div class="bar"><h1>Insights</h1></div><div class="view"><div class="empty"><h3>Couldn't load insights</h3><p>${e.message}</p></div></div>`); return; }
  const fc = ins.forecast, h = ins.health;
  if (!ins.total_spend_30d) {
    paint(host, html`<div class="bar"><h1>Insights</h1></div><div class="view"><div class="empty"><h3>No spending yet</h3><p>Make a payment and your stories, forecast and tips appear here.</p><button class="btn" data-go="pay">Pay someone</button></div></div>`);
    return;
  }
  const top = ins.categories.slice(0, 7), rest = ins.categories.slice(7);
  const rows = top.map((c, i) => ({ ...c, cls: 's' + i }));
  if (rest.length) rows.push({ category: `${rest.length} smaller categories`, amount: rest.reduce((s, c) => s + c.amount, 0), share: rest.reduce((s, c) => s + c.share, 0), change_pct: undefined, cls: 's8' });
  const peaks = new Set(ins.anomaly_days.map((d) => d.date));
  const bars = ins.daily.slice(-21).map((d) => ({ short: dshort(d.date), label: dshort(d.date), value: d.amount, kind: peaks.has(d.date) ? 'peak' : '' }));
  if (fc.available) fc.next_days.forEach((d) => bars.push({ short: dshort(d.date), label: dshort(d.date) + ' (forecast)', value: d.amount, kind: 'fc' }));
  const weakest = [...h.factors].sort((a, b) => a.points / a.max - b.points / b.max)[0];
  const t0 = ins.categories[0], maxCat = Math.max(...ins.categories.slice(0, 5).map((c) => c.amount));
  const fmax = fc.available ? Math.max(...fc.next_days.map((d) => d.amount), 1) : 1;

  paint(host, html`
    <div class="bar"><h1>Insights</h1><button class="icon-btn" data-go="ask" aria-label="Ask AI">${icon('sparkle')}</button></div>
    <div class="view">
      <p class="muted">Your last 30 days, as the AI sees them. Swipe the cards.</p>
      <div class="stories" role="list">
        <article class="story s-indigo" role="listitem"><p>Last 30 days</p><div><div class="huge">${rupees(ins.total_spend_30d)}</div><p>spent, about ${rupees(ins.avg_daily)} a day</p></div><small>This month so far ${rupees(ins.month_to_date)}</small></article>
        <article class="story s-gold" role="listitem"><p>Most of it went to</p><div><div class="mid">${t0.category}</div><p>${rupees(t0.amount)} · ${Math.round(t0.share * 100)}% of your spending</p></div>
          <div class="mini-bars" aria-hidden="true">${ins.categories.slice(0, 5).map((c, i) => html`<i class="${i === 0 ? 'hi' : ''}" style="height:${Math.max(8, (c.amount / maxCat) * 100)}%"></i>`)}</div></article>
        ${fc.available ? html`<article class="story s-ink" role="listitem"><p>Next 7 days</p><div><div class="huge">${rupees(fc.next_7_total)}</div><p>is what the AI expects you to spend</p></div>
          <div><div class="mini-bars" aria-hidden="true">${fc.next_days.map((d) => html`<i class="hi" style="height:${Math.max(8, (d.amount / fmax) * 100)}%"></i>`)}</div><small>Month-end projection ${rupees(fc.month_end_projection)}</small></div></article>` : ''}
        <article class="story s-soft" role="listitem"><p>Financial health</p><div class="row-flex" style="gap:18px">${ring(h.score, 100)}<div><div class="mid">${h.label}</div><small style="opacity:1;color:var(--ink-2)">Weakest: ${weakest.name.toLowerCase()}</small></div></div><small style="opacity:1;color:var(--ink-3)">${weakest.note}</small></article>
        ${ins.subscriptions.length ? html`<article class="story s-indigo" role="listitem"><p>Recurring payments</p><div><div class="huge">${rupees(ins.subscriptions.reduce((s, x) => s + x.per_month, 0))}</div><p>a month across ${plural(ins.subscriptions.length, 'payment', 'payments')}</p></div><small>${ins.subscriptions.slice(0, 3).map((s) => s.name).join(' · ')}</small></article>` : ''}
      </div>

      <div class="section-h"><h2>Where it went</h2></div>
      <div class="panel">${rows.map((c) => html`<div class="cat-row"><span class="dot ${c.cls}"></span><span>${c.category}</span><b class="num">${money(c.amount)}</b><div class="bar-track"><i class="${c.cls}" style="width:${Math.max(3, c.share * 100).toFixed(1)}%"></i></div></div>`)}</div>

      <div class="section-h"><h2>Day by day</h2></div>
      <div class="panel">${barChart(bars, { label: (b) => b.short, title: (b) => `${b.label}: ${money(b.value)}`, aria: 'Daily spending with a 7 day forecast' })}
        <p class="hint" style="margin-top:6px">${fc.available ? html`Faded bars are the AI forecast (${fc.method}). ` : ''}${peaks.size ? 'Red bars are unusually high days.' : ''}</p></div>

      <div class="section-h"><h2>Health score</h2></div>
      <div class="panel">${h.factors.map((f) => html`<div style="margin-bottom:12px"><div class="row-flex between small"><span>${f.name}</span><b class="num">${f.points}/${f.max}</b></div>${meter(f.points, f.max, 'brand')}<p class="hint" style="margin-top:4px">${f.note}</p></div>`)}</div>

      ${ins.subscriptions.length ? html`<div class="section-h"><h2>Recurring</h2></div><ul class="list">${ins.subscriptions.map((s) => html`<li><div class="row">${avatar(s.name)}<div style="min-width:0"><div class="t">${s.name}</div><div class="s">${s.every} · next around ${dateShort(s.next_expected + 'T12:00:00')}</div></div><div class="amt">${money(s.amount)}</div></div></li>`)}</ul>` : ''}

      <div class="section-h"><h2>Notes from the AI</h2></div>
      <div class="panel"><ul class="reasons">${ins.tips.map((t) => html`<li>${t}</li>`)}</ul></div>
      <div class="section-h"><h2>How the AI works</h2></div>
      <details class="panel" id="model"><summary style="cursor:pointer;font-weight:650">Model card</summary><div id="model-body" class="stack small" style="margin-top:10px"><p class="muted">Loading…</p></div></details>
    </div>`);

  $('#model', host).addEventListener('toggle', async (e) => {
    if (!e.target.open || e.target.dataset.done) return;
    e.target.dataset.done = '1';
    try {
      const m = await api('/ai/model');
      paint($('#model-body', host), html`
        <p><b>Fraud check.</b> ${m.fraud.engine} plus transparent rules. ${m.fraud.formula}. Trained on ${m.fraud.trained_on.synthetic} synthetic normal payments and ${m.fraud.trained_on.real} real ones. Low below ${m.fraud.thresholds.medium}, OTP from ${m.fraud.thresholds.medium}, held for review from ${m.fraud.thresholds.high}.</p>
        <p><b>Categories.</b> ${m.categorizer.type}, ${m.categorizer.seed_phrases} seed phrases, ${m.categorizer.learned_from_user_corrections} learned from corrections.</p>
        <p><b>Forecast.</b> ${m.forecast.method}, ${m.forecast.horizon_days} days ahead.</p>
        <p><b>Assistant.</b> ${m.assistant.mode}${m.assistant.model ? ' (' + m.assistant.model + ')' : ''}. Languages: ${m.assistant.languages.join(', ')}.</p>`);
    } catch (err) { paint($('#model-body', host), html`<p class="err">${err.message}</p>`); }
  });
}
