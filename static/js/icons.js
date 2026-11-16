// Hand-drawn 24px stroke icons (no icon library). icon('home') returns an inline <svg>.
import { raw } from './ui.js';

const P = {
  home: '<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.8V20h13V9.8"/><path d="M10 20v-5.5h4V20"/>',
  activity: '<path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2z"/><path d="M9.5 8h5M9.5 12h5"/>',
  send: '<path d="M7 17 17 7"/><path d="M8.5 7H17v8.5"/>',
  add: '<path d="M12 5v14M5 12h14"/>',
  withdraw: '<path d="M12 4v11"/><path d="m7.5 11 4.5 4.5 4.5-4.5"/><path d="M5 20h14"/>',
  chart: '<path d="M5 20V11M12 20V4M19 20v-6"/>',
  user: '<circle cx="12" cy="8" r="3.8"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
  sparkle: '<path d="m12 3 1.9 5.3L19 10.2l-5.1 1.9L12 17.5l-1.9-5.4L5 10.2l5.1-1.9z"/><path d="m19 16 .7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z"/>',
  shield: '<path d="M12 3 5 5.8v5.4c0 4.4 2.9 7.6 7 9.3 4.1-1.7 7-4.9 7-9.3V5.8z"/><path d="m8.8 11.9 2.2 2.2 4.2-4.4"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  qr: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h3v3h-3zM20 14v3M20 20h-3M14 20v.01"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  chevR: '<path d="m9 6 6 6-6 6"/>', chevL: '<path d="m15 6-6 6 6 6"/>', chevD: '<path d="m6 9 6 6 6-6"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  eyeOff: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/><path d="m4 4 16 16"/>',
  lock: '<rect x="5.5" y="11" width="13" height="9.5" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>',
  cpu: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9.5 3.5V7M14.5 3.5V7M9.5 17v3.5M14.5 17v3.5M3.5 9.5H7M3.5 14.5H7M17 9.5h3.5M17 14.5h3.5"/>',
  download: '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 20h14"/>',
  share: '<path d="M12 15V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M5 13.5V20h14v-6.5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  settings: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  logout: '<path d="M10 4.5H6A1.5 1.5 0 0 0 4.5 6v12A1.5 1.5 0 0 0 6 19.5h4"/><path d="m15 8 4 4-4 4M19 12H9.5"/>',
  store: '<path d="M4.5 9.5 6 4.5h12l1.5 5"/><path d="M5 9.5v10h14v-10"/><path d="M4.5 9.5a2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 0 5 0"/><path d="M10 19.5v-5h4v5"/>',
  repeat: '<path d="m17 3 3.5 3.5L17 10"/><path d="M20.5 6.5H9A5 5 0 0 0 4 11.5"/><path d="m7 21-3.5-3.5L7 14"/><path d="M3.5 17.5H15a5 5 0 0 0 5-5"/>',
  backspace: '<path d="M20.5 5.5H9.5L3 12l6.5 6.5h11z"/><path d="m13.5 9.5 4 4M17.5 9.5l-4 4"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.01"/>',
  alert: '<path d="M12 3.5 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.01"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  hourglass: '<path d="M7 3.5h10M7 20.5h10"/><path d="M8 3.5c0 4 4 5 4 8.5s-4 4.5-4 8.5M16 3.5c0 4-4 5-4 8.5s4 4.5 4 8.5"/>',
  tag: '<path d="M3.5 12.5 12 4h7.5v7.5L11 20z"/><circle cx="15.5" cy="8.5" r="1.3"/>',
  people: '<circle cx="9" cy="8.5" r="3.3"/><path d="M2.8 20a6.2 6.2 0 0 1 12.4 0"/><path d="M16 5.5a3.3 3.3 0 0 1 0 6M18.5 14.5a6.2 6.2 0 0 1 2.7 5.5"/>',
  book: '<path d="M5 4.5h10.5A3.5 3.5 0 0 1 19 8v12.5H8.5A3.5 3.5 0 0 1 5 17z"/><path d="M5 17a3.5 3.5 0 0 1 3.5-3.5H19"/>',
};

export const icon = (name, cls = '') =>
  raw(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"${cls ? ` class="${cls}"` : ''}>${P[name] || ''}</svg>`);

/** The Smart Wallet mark: a wallet with a gold clasp. Uses currentColor so it works on any background. */
export const logo = () => raw('<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="3" y="8" width="26" height="19" rx="5" fill="currentColor"/><path d="M3 13a5 5 0 0 1 5-5h14l-3 5z" fill="currentColor" opacity=".55"/><circle cx="23" cy="19" r="2.5" fill="#F2B01E"/></svg>');
