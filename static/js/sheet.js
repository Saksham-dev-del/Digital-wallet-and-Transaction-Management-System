// Bottom sheets. They live inside the phone-width frame (#layer), so they never spill across a wide desktop.
import { reducedMotion } from './ui.js';

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select, textarea, [href], [tabindex]:not([tabindex="-1"])';

export function openSheet(content, { onMount, onClose, label = 'Dialog' } = {}) {
  const layer = document.getElementById('layer') || document.body;
  const scrim = document.createElement('div');
  scrim.className = 'scrim';
  const sheet = document.createElement('div');
  sheet.className = 'sheet';
  sheet.setAttribute('role', 'dialog'); sheet.setAttribute('aria-modal', 'true'); sheet.setAttribute('aria-label', label);
  const grab = document.createElement('div');
  grab.className = 'grab'; grab.setAttribute('aria-hidden', 'true');
  const body = document.createElement('div');
  body.className = 'sheet-body';
  sheet.append(grab, body);
  scrim.append(sheet);
  layer.append(scrim);

  const previous = document.activeElement;
  let closed = false;
  const onKey = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); return; }
    if (e.key !== 'Tab') return;
    const items = [...sheet.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', onKey, true);
    scrim.classList.add('leaving');
    setTimeout(() => scrim.remove(), reducedMotion() ? 0 : 200);
    if (previous && previous.focus && document.contains(previous)) previous.focus();
    if (onClose) onClose();
  }
  document.addEventListener('keydown', onKey, true);
  scrim.addEventListener('mousedown', (e) => { if (e.target === scrim) close(); });

  // drag the handle down to dismiss
  let startY = null;
  grab.style.touchAction = 'none';
  grab.addEventListener('pointerdown', (e) => { startY = e.clientY; grab.setPointerCapture(e.pointerId); sheet.style.transition = 'none'; });
  grab.addEventListener('pointermove', (e) => { if (startY !== null) sheet.style.transform = `translateY(${Math.max(0, e.clientY - startY)}px)`; });
  const endDrag = (e) => {
    if (startY === null) return;
    const dy = e.clientY - startY;
    startY = null; sheet.style.transition = 'transform .2s';
    if (dy > 110) close(); else sheet.style.transform = '';
  };
  grab.addEventListener('pointerup', endDrag); grab.addEventListener('pointercancel', endDrag);

  const handle = {
    el: body, close,
    setContent(tpl, mountFn) { body.innerHTML = tpl.s; wire(); if (mountFn) mountFn(body, handle); focusFirst(); },
  };
  function wire() { body.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', close)); }
  function focusFirst() { const f = body.querySelector('input, select, textarea') || body.querySelector('button'); if (f) f.focus({ preventScroll: true }); }
  body.innerHTML = content.s;
  wire();
  focusFirst();
  if (onMount) onMount(body, handle);
  return handle;
}
