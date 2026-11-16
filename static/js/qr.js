// QR codes for "Receive money". The encoder is the MIT-licensed qrcode-generator library (js/vendor/qrcode.js).
import qrcode from './vendor/qrcode.js';
import { raw } from './ui.js';

export function qrSvg(text, { margin = 2 } = {}) {
  const q = qrcode(0, 'M');
  q.addData(text);
  q.make();
  const n = q.getModuleCount();
  let d = '';
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) d += `M${c + margin},${r + margin}h1v1h-1z`;
  const size = n + margin * 2;
  return raw(`<svg viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges" role="img" aria-label="QR code"><rect width="${size}" height="${size}" fill="#fff"/><path d="${d}" fill="#11142E"/></svg>`);
}
