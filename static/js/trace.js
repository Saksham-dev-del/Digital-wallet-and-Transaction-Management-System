// Renders the server's step-by-step trace of a payment (light version for the receipt screen).
import { html } from './ui.js';

export const LAYER_NAMES = { API: 'request', AI: 'AI', OS: 'operating system', DBMS: 'database', CACHE: 'cache', FILE: 'file system' };

export const traceHtml = (steps) => html`<ul class="trace-light">${steps.map((s) => html`<li><span class="lay lay-${s.layer}">${s.layer}</span><span><b>${s.title}</b>${s.detail ? html`<span class="det">${s.detail}</span>` : ''}</span></li>`)}</ul>`;
