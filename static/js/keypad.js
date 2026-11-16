// The big on-screen number pad used by Pay, Add money and Withdraw (the physical keyboard works too).
import { html, esc } from './ui.js';
import { icon } from './icons.js';

export const keypadHtml = () => html`<div class="keypad" role="group" aria-label="Number pad">${['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', 'back'].map((k) =>
  (k === 'back' ? html`<button type="button" data-k="back" aria-label="Delete">${icon('backspace')}</button>` : html`<button type="button" data-k="${k}">${k}</button>`))}</div>`;

export function fmtTyped(str) {
  if (!str) return '';
  const [whole, frac] = str.split('.');
  const w = whole ? Number(whole).toLocaleString('en-IN') : '0';
  return frac === undefined ? w : `${w}.${frac}`;
}

/** root contains an .amt-display and the keypad. Returns { value, set(), dispose() }. */
export function bindAmount(root, { onChange, max = 7 } = {}) {
  let value = '';
  const display = root.querySelector('.amt-display');
  function render() {
    display.classList.toggle('empty-amt', !value);
    display.innerHTML = `<span class="cur">₹</span><span class="digits">${esc(value ? fmtTyped(value) : '0')}</span><span class="caret"></span>`;
    display.setAttribute('aria-label', `Amount: ${value || 0} rupees`);
    if (onChange) onChange(value);
  }
  function press(k) {
    if (k === 'back') value = value.slice(0, -1);
    else if (k === '.') { if (!value.includes('.')) value = (value || '0') + '.'; }
    else if (/^\d$/.test(k)) {
      const [whole, frac] = value.split('.');
      if (frac !== undefined) { if (frac.length < 2) value += k; }
      else if (whole.length < max) value = (value === '0' ? '' : value) + k;
    }
    render();
  }
  root.addEventListener('click', (e) => { const b = e.target.closest('[data-k]'); if (b) press(b.dataset.k); });
  const onKey = (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest && e.target.closest('input, textarea, select')) return;
    if (document.querySelector('.scrim')) return;                       // a sheet is open
    if (/^\d$/.test(e.key) || e.key === '.') press(e.key);
    else if (e.key === 'Backspace') press('back');
  };
  document.addEventListener('keydown', onKey);
  render();
  return { get value() { return value; }, set(v) { value = String(v || ''); render(); }, dispose() { document.removeEventListener('keydown', onKey); } };
}
