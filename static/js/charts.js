// Hand-drawn SVG charts (no libraries). Colours come from CSS classes so dark mode just works.
import { raw, esc, money } from './ui.js';

export function barChart(bars, { height = 150, width = 380, label = (b) => b.label, title = (b) => `${b.label}: ${money(b.value)}`, aria = 'Bar chart' } = {}) {
  const pad = { l: 14, r: 14, t: 16, b: 22 };
  const max = Math.max(1, ...bars.map((b) => b.value));
  const bw = (width - pad.l - pad.r) / bars.length;
  const h = height - pad.t - pad.b;
  const rects = bars.map((b, i) => {
    const bh = Math.max(b.value > 0 ? 1.5 : 0, (b.value / max) * h);
    return `<rect class="bar-rect ${b.kind || ''}" x="${(pad.l + i * bw + bw * 0.14).toFixed(1)}" y="${(pad.t + h - bh).toFixed(1)}" width="${(bw * 0.72).toFixed(1)}" height="${bh.toFixed(1)}" rx="1"><title>${esc(title(b))}</title></rect>`;
  }).join('');
  const every = Math.ceil(bars.length / 6);
  const ticks = bars.map((b, i) => (i % every === 0 ? `<text x="${(pad.l + i * bw + bw / 2).toFixed(1)}" y="${height - 6}" text-anchor="middle">${esc(label(b))}</text>` : '')).join('');
  return raw(`<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(aria)}" style="width:100%;height:auto"><line class="axis" x1="${pad.l}" x2="${width - pad.r}" y1="${pad.t + h}" y2="${pad.t + h}"/>${rects}${ticks}<text x="${pad.l}" y="10">${esc(money(max))}</text></svg>`);
}

function arc(cx, cy, r1, r2, a0, a1, cls, title) {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const p = (r, a) => [(cx + r * Math.cos(a)).toFixed(2), (cy + r * Math.sin(a)).toFixed(2)];
  const [x0, y0] = p(r2, a0), [x1, y1] = p(r2, a1), [x2, y2] = p(r1, a1), [x3, y3] = p(r1, a0);
  return `<path class="${cls}" d="M${x0},${y0} A${r2},${r2} 0 ${large} 1 ${x1},${y1} L${x2},${y2} A${r1},${r1} 0 ${large} 0 ${x3},${y3} Z"><title>${esc(title)}</title></path>`;
}

export function donut(items, { size = 190, inner = 0.6, centre = '' } = {}) {
  const total = items.reduce((s, i) => s + i.value, 0);
  const c = size / 2, r2 = c - 4, r1 = r2 * inner;
  let a = -Math.PI / 2;
  const paths = [];
  for (const it of items) {
    if (it.value <= 0) continue;
    const sweep = Math.min((it.value / total) * 2 * Math.PI, 2 * Math.PI - 0.0001);
    paths.push(arc(c, c, r1, r2, a, a + sweep, it.cls, it.title));
    a += (it.value / total) * 2 * Math.PI;
  }
  return raw(`<svg class="chart" viewBox="0 0 ${size} ${size}" role="img" aria-label="Spending by category" style="width:100%;max-width:${size}px;height:auto">${paths.join('')}<text x="${c}" y="${c + 4}" text-anchor="middle" style="font-size:13px;font-weight:700;fill:var(--ink)">${esc(centre)}</text></svg>`);
}

export function gantt(segments, total, order) {
  const width = 700, pad = 8, unit = (width - 2 * pad) / total;
  let lastTick = -99;
  const bars = [], ticks = [];
  const tick = (t) => {
    const x = pad + t * unit;
    if (x - lastTick >= 18) { ticks.push(`<text class="tick" x="${x.toFixed(1)}" y="62" text-anchor="middle">${t}</text>`); lastTick = x; }
  };
  for (const s of segments) {
    const x = pad + s.start * unit, w = (s.end - s.start) * unit;
    const cls = s.pid === 'idle' ? 's8' : 's' + (Math.max(0, order.indexOf(s.pid)) % 8);
    bars.push(`<rect class="${cls}" x="${x.toFixed(1)}" y="8" width="${w.toFixed(1)}" height="38" stroke="var(--surface)" stroke-width="1.5"><title>${esc(s.pid)}: ${s.start} to ${s.end}</title></rect>`);
    if (w > 16) bars.push(`<text x="${(x + w / 2).toFixed(1)}" y="31" text-anchor="middle">${esc(s.pid === 'idle' ? '' : s.pid)}</text>`);
    tick(s.start);
  }
  tick(total);
  return raw(`<svg class="chart gantt" viewBox="0 0 ${width} 70" role="img" aria-label="Gantt chart" style="width:100%;height:auto">${bars.join('')}${ticks.join('')}</svg>`);
}

/** Wait-for graph: an arrow from each waiting thread to the thread holding the lock it needs. */
export function waitForGraph(cycle) {
  const n = cycle.length, W = 420, H = n === 2 ? 130 : 230, cx = W / 2, cy = H / 2, R = n === 2 ? 120 : 82, NR = 28;
  const pos = {};
  if (n === 2) {
    pos[cycle[0].thread] = [cx - R, cy];
    pos[cycle[1].thread] = [cx + R, cy];
  } else {
    cycle.forEach((c, i) => {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
      pos[c.thread] = [cx + R * Math.cos(a), cy + R * Math.sin(a)];
    });
  }
  const edges = cycle.map((c, i) => {
    const from = pos[c.thread], to = pos[c.held_by];
    if (!from || !to) return '';
    const dx = to[0] - from[0], dy = to[1] - from[1], len = Math.hypot(dx, dy) || 1;
    const off = n === 2 ? -16 : 0;                                         // two parallel arrows for a 2-cycle (the normal flips with direction)
    const nx = (-dy / len) * off, ny = (dx / len) * off;
    const x1 = from[0] + (dx / len) * NR + nx, y1 = from[1] + (dy / len) * NR + ny;
    const x2 = to[0] - (dx / len) * (NR + 5) + nx, y2 = to[1] - (dy / len) * (NR + 5) + ny;
    return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="var(--bad)" stroke-width="2" marker-end="url(#arr)"/>` +
      `<text x="${((x1 + x2) / 2).toFixed(1)}" y="${((y1 + y2) / 2 + (n === 2 && i === 1 ? 18 : -8)).toFixed(1)}" text-anchor="middle">waits for ${esc(c.waits_for)}</text>`;
  }).join('');
  const nodes = Object.entries(pos).map(([name, [x, y]]) =>
    `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${NR}" fill="var(--brand-tint)" stroke="var(--brand)" stroke-width="2"/><text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="middle" style="fill:var(--ink);font-weight:650">${esc(name)}</text>`).join('');
  return raw(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Wait-for graph showing a cycle" style="width:100%;max-width:${W}px;height:auto"><defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--bad)"/></marker></defs>${edges}${nodes}</svg>`);
}

export const meter = (value, max, tone = '') =>
  raw(`<div class="meter ${tone}" role="meter" aria-valuenow="${Math.round(value)}" aria-valuemin="0" aria-valuemax="${max}"><i style="width:${Math.max(0, Math.min(100, (value / max) * 100)).toFixed(1)}%"></i></div>`);

/** A progress ring (health score, limits). The SVG is rotated by CSS so progress starts at 12 o'clock. */
export function ring(value, max, { color = 'var(--brand)', stroke = 12 } = {}) {
  const r = 60 - stroke / 2 - 2, c = 2 * Math.PI * r, frac = Math.max(0, Math.min(1, value / max));
  return raw(`<div class="ring"><svg viewBox="0 0 120 120" aria-hidden="true"><circle cx="60" cy="60" r="${r}" fill="none" stroke="currentColor" stroke-opacity=".18" stroke-width="${stroke}"/><circle cx="60" cy="60" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${(c * frac).toFixed(1)} ${c.toFixed(1)}"/></svg><b>${Math.round(value)}</b></div>`);
}
