import { state } from '../state.js';
import { html, $, toast, copyText } from '../ui.js';
import { icon } from '../icons.js';
import { openSheet } from '../sheet.js';
import { qrSvg } from '../qr.js';

export function openReceive() {
  const u = state.user;
  const payload = `swallet://pay?pa=${encodeURIComponent(u.wallet_code)}&pn=${encodeURIComponent(u.full_name)}`;
  openSheet(html`
    <div class="center"><h2>Receive money</h2><p class="muted small">Anyone with Smart Wallet can pay you with this code or your wallet ID.</p>
      <div class="qr-box">${qrSvg(payload)}</div>
      <b style="font:700 18px var(--display)">${u.full_name}</b><div class="mono muted small">${u.wallet_code}</div></div>
    <div class="actions"><button class="btn block" id="rc-copy">${icon('copy')} Copy wallet ID</button><button class="btn ghost block" data-close>Close</button></div>`,
  { label: 'Receive money', onMount: (b) => { $('#rc-copy', b).addEventListener('click', async () => toast((await copyText(u.wallet_code)) ? 'Wallet ID copied.' : 'Could not copy.', 'good')); } });
}
