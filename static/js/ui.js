// UI toolkit: auto-escaping html`` templates, formatting, feedback, avatars, preferences.
const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => MAP[c]);

export class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s));

function part(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(part).join('');
  if (v === false || v === null || v === undefined) return '';
  return esc(v);
}
/** Tagged template: every ${value} is HTML-escaped unless it is itself an html`` result. */
export function html(strings, ...values) {
  let out = '';
  for (let i = 0; i < strings.length; i++) { out += strings[i]; if (i < values.length) out += part(values[i]); }
  return new Raw(out);
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export function paint(el, tpl) { if (!el) return el; el.innerHTML = tpl instanceof Raw ? tpl.s : String(tpl); return el; }

// ------------------------------------------------------------------ formatting
export const money = (paise) => '₹' + (Number(paise) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const rupees = (paise) => '₹' + Math.round(Number(paise) / 100).toLocaleString('en-IN');
export function moneyParts(paise) {
  const p = Math.abs(Math.round(Number(paise)));
  return { whole: Math.floor(p / 100).toLocaleString('en-IN'), frac: String(p % 100).padStart(2, '0') };
}
export const dateShort = (iso) => new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
export const dateTime = (iso) => new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
export const timeShort = (iso) => new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase();
export function dayLabel(iso) {
  const d = new Date(iso), now = new Date(), y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return 'Today';
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) });
}
export const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const reducedMotion = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

export const CATEGORIES = ['Food & Dining', 'Groceries', 'Transport', 'Shopping', 'Bills & Recharge', 'Entertainment',
  'Health', 'Education', 'Rent & Housing', 'Travel', 'Friends & Family', 'Other'];

// ------------------------------------------------------------------ feedback
export function toast(message, kind = 'info', ms = 3800) {
  const box = document.getElementById('toasts');
  if (!box) return;
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = message;
  box.append(el);
  setTimeout(() => el.remove(), ms);
}
export function debounce(fn, ms = 400) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
export const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : 'k-' + Date.now() + '-' + Math.random().toString(16).slice(2));
export async function busy(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } finally { if (btn) btn.disabled = false; }
}
export const errText = (e) => (e && e.message ? e.message : 'Something went wrong.');

// ------------------------------------------------------------------ avatars (initials, stable colour per name; merchants get brand colours)
const BRAND = { swiggy: '#FC8019', zomato: '#E23744', 'uber india': '#111111', netflix: '#E50914', amazon: '#232F3E', 'jio prepaid': '#0A57D1',
  'apollo pharmacy': '#00829B', bigbasket: '#6FAE1E', 'campus canteen': '#8A5A44', bookmyshow: '#D1203F', 'hostel office': '#5B6B8C' };
function hashStr(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); }
export function initials(name) {
  const parts = String(name || '?').trim().split(/\s+/);
  return ((parts[0] || '?')[0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}
export function avatar(name, { size = 44, merchant = false } = {}) {
  const brand = BRAND[String(name).toLowerCase()];
  merchant = merchant || !!brand;
  return raw(`<span class="av${merchant ? ' sq' : ''}" data-c="${hashStr(String(name)) % 8}"${brand ? ' data-brand' : ''} style="--s:${size}px${brand ? `;--av-bg:${brand}` : ''}" aria-hidden="true">${esc(initials(name))}</span>`);
}

// ------------------------------------------------------------------ preferences + theme
export const prefs = {
  get(key, dflt) { try { const v = localStorage.getItem('sw_' + key); return v === null ? dflt : v; } catch { return dflt; } },
  set(key, value) { try { localStorage.setItem('sw_' + key, value); } catch { /* private mode */ } },
};
export function applyTheme() {
  const pref = prefs.get('theme', 'system');
  const dark = pref === 'dark' || (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
}
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.append(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  return ok;
}
