import { api, auth, setUnauthorizedHandler } from './api.js';
import { state, back } from './state.js';
import { html, paint, $, $$, toast, applyTheme } from './ui.js';
import { icon, logo } from './icons.js';
import { hoodPanel } from './hood.js';
import * as authView from './views/auth.js';
import * as home from './views/home.js';
import * as pay from './views/pay.js';
import * as money from './views/money.js';
import * as activity from './views/activity.js';
import * as txn from './views/txn.js';
import * as insights from './views/insights.js';
import * as ask from './views/ask.js';
import * as profile from './views/profile.js';
import * as scheduled from './views/scheduled.js';
import * as oslab from './views/oslab.js';
import * as admin from './views/admin.js';

const APP = {
  home: { view: home, tab: 'home' }, activity: { view: activity, tab: 'activity' }, insights: { view: insights, tab: 'insights' }, profile: { view: profile, tab: 'profile' },
  pay: { view: pay, push: true }, add: { view: money, push: true }, withdraw: { view: money, push: true }, txn: { view: txn, push: true },
  ask: { view: ask, push: true }, scheduled: { view: scheduled, push: true },
};
const CONSOLE = { lab: { view: oslab }, admin: { view: admin, admin: true } };

const root = document.getElementById('root');
let mode = null, dispose = null, hoodDispose = null, token = 0;

// ------------------------------------------------------------------ routing helpers
function parse() {
  const [path, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
  const segs = path.split('/').filter(Boolean).map((s) => { try { return decodeURIComponent(s); } catch { return s; } });
  return { name: segs[0] || '', params: segs.slice(1), query: new URLSearchParams(query) };
}
const tabLink = (id, ic, label) => html`<a class="tab" href="#/${id}" data-tab="${id}">${icon(ic)}<span>${label}</span></a>`;

// ------------------------------------------------------------------ the phone-width app stage
function railLeft() {
  if (!state.user) {
    return html`<div class="wmark">${logo()}Smart Wallet</div><h1>A wallet you can open up.</h1><p>Real payments, an AI shield on every one, and a live look at the locks, transactions and logs underneath.</p>
      <ul class="try"><li><div class="a"><span class="i">${icon('user')}</span><span><b>Student demo</b><span>aarav@wallet.test · Demo@1234</span></span></div></li>
      <li><div class="a"><span class="i">${icon('shield')}</span><span><b>Admin demo</b><span>admin@wallet.test · Admin@123</span></span></div></li></ul>`;
  }
  const item = (href, ic, title, sub) => html`<li><a href="${href}"><span class="i">${icon(ic)}</span><span><b>${title}</b><span>${sub}</span></span></a></li>`;
  return html`<div class="wmark">${logo()}Smart Wallet</div><h1>A wallet you can open up.</h1><p>Pay like in any app. Then look inside: every step the server takes is streamed on the right.</p>
    <ul class="try">
      ${item('#/pay/rohan%40swallet?amount=250&note=dinner%20split', 'send', 'Pay Rohan ₹250', 'The AI shield clears it instantly')}
      ${item('#/pay/priya%40swallet?amount=6000&note=hostel%20fees', 'lock', 'Pay Priya ₹6,000', 'Asks for an OTP first')}
      ${item('#/ask?q=mera%20balance%20kitna%20hai', 'sparkle', 'Ask in Hinglish', '"mera balance kitna hai"')}
      ${item('#/lab/deadlock', 'cpu', 'Watch a deadlock break', 'Two transfers, one cycle, one victim')}
      <li><div class="a"><span class="i">${icon('shield')}</span><span><b>Hold a risky payment</b><span>Register a second account, pay it about ₹13,000, then approve it as admin</span></span></div></li>
    </ul>
    <div class="rail-foot"><a class="btn ghost" href="#/lab/overview">Lab console</a>${state.user.role === 'admin' ? html`<a class="btn ghost" href="#/admin">Admin console</a>` : ''}</div>`;
}

function buildStage() {
  paint(root, html`
    <div class="stage" id="stage">
      <aside class="rail rail-left" id="rail-left"></aside>
      <div class="frame" id="frame">
        <main class="screens" id="screens" tabindex="-1"></main>
        <nav class="tabbar" aria-label="Main">${tabLink('home', 'home', 'Home')}${tabLink('activity', 'activity', 'Activity')}
          <a class="tab pay" href="#/pay" data-tab="pay" aria-label="Pay"><span class="pay-btn">${icon('send')}</span><span>Pay</span></a>${tabLink('insights', 'chart', 'Insights')}${tabLink('profile', 'user', 'Profile')}</nav>
        <div class="layer" id="layer"></div>
      </div>
      <aside class="rail rail-right" id="rail-right"></aside>
    </div>`);
  mode = 'stage';
}
function syncRails() {
  paint($('#rail-left', root), railLeft());
  const wide = window.matchMedia('(min-width: 1200px)').matches;
  if (hoodDispose) { hoodDispose(); hoodDispose = null; }
  paint($('#rail-right', root), '');
  if (state.user && wide) hoodDispose = hoodPanel($('#rail-right', root));
}

// ------------------------------------------------------------------ the lab console (OS lab + admin)
function buildConsole() {
  if (hoodDispose) { hoodDispose(); hoodDispose = null; }
  paint(root, html`
    <div class="console">
      <header class="console-bar"><span class="wmark">${logo()}Smart Wallet</span><span class="mode">lab console</span>
        <nav class="console-tabs" aria-label="Console"><a href="#/lab/overview" data-c="lab">OS lab</a>${state.user.role === 'admin' ? html`<a href="#/admin" data-c="admin">Admin</a>` : ''}</nav>
        <a class="btn ghost small" href="#/home">Back to the app</a></header>
      <main class="console-main" id="console-main" tabindex="-1"></main>
    </div>`);
  mode = 'console';
}

// ------------------------------------------------------------------ router
async function route() {
  state.routeCount++;
  if (dispose) { try { dispose(); } catch { /* ignore */ } dispose = null; }
  $$('.scrim').forEach((s) => s.remove());
  const r = parse(), mine = ++token;

  if (!state.user) {
    if (mode !== 'stage') buildStage();
    syncRails();
    $('#frame', root).classList.add('no-tabs');
    const holder = document.createElement('div');
    holder.className = 'holder';
    $('#screens', root).replaceChildren(holder);
    authView.mount(holder, { onAuthed: () => { location.hash = '#/home'; route(); } });
    return;
  }
  if (r.name === 'login') { location.hash = '#/home'; return; }

  let target, view, container;
  if (CONSOLE[r.name] && (!CONSOLE[r.name].admin || state.user.role === 'admin')) {
    if (mode !== 'console') buildConsole();
    $$('.console-tabs a', root).forEach((a) => (a.dataset.c === r.name ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
    container = $('#console-main', root); view = CONSOLE[r.name].view; target = r.name === 'admin' ? 'Admin console' : 'Lab console';
  } else {
    const def = APP[r.name] || APP.home;
    const wasStage = mode === 'stage';
    if (!wasStage) buildStage();
    if (!wasStage || !$('#rail-left', root).firstChild || (hoodDispose === null && window.matchMedia('(min-width: 1200px)').matches)) syncRails();
    const frame = $('#frame', root);
    frame.classList.toggle('no-tabs', !!def.push);
    $$('.tab', root).forEach((a) => (def.tab && a.dataset.tab === def.tab ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
    container = $('#screens', root); view = def.view; target = (APP[r.name] ? r.name : 'home');
    container.scrollTop = 0;
  }
  const holder = document.createElement('div');
  holder.className = 'holder';
  container.replaceChildren(holder);
  paint(holder, html`<div class="view"><div class="skel" style="margin-top:20px"></div><div class="skel"></div></div>`);
  document.title = `${target[0].toUpperCase() + target.slice(1)} · Smart Wallet`;
  try {
    const d = await view.mount(holder, { name: r.name, params: r.params, query: r.query });
    if (mine !== token) { if (typeof d === 'function') d(); return; }   // the user moved on while this view was loading
    dispose = typeof d === 'function' ? d : null;
  } catch (e) {
    if (mine !== token) return;
    console.error(e);
    paint(holder, html`<div class="view"><div class="empty"><h3>Something went wrong</h3><p>${e.message}</p><button class="btn" data-go="home">Back home</button></div></div>`);
  }
}

// ------------------------------------------------------------------ global events
document.addEventListener('click', (e) => {
  const back_ = e.target.closest('[data-back]');
  if (back_) { e.preventDefault(); back(); return; }
  const tab = e.target.closest('a.tab, a.btn, .console-tabs a');
  if (tab && tab.getAttribute('href') === location.hash) { e.preventDefault(); route(); return; }    // clicking where you already are refreshes the view
  const t = e.target.closest('[data-go]');
  if (!t) return;
  e.preventDefault();
  const hash = '#/' + t.dataset.go;
  if (location.hash === hash) route(); else location.hash = hash;
});
window.addEventListener('hashchange', route);
window.addEventListener('resize', (() => { let t; return () => { clearTimeout(t); t = setTimeout(() => { if (mode === 'stage' && state.user) { const wide = window.matchMedia('(min-width: 1200px)').matches; if (wide && !hoodDispose) syncRails(); if (!wide && hoodDispose) syncRails(); } }, 200); }; })());
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);

async function signOut() {
  try { await api('/auth/logout', { method: 'POST' }); } catch { /* already gone */ }
  auth.clear(); state.user = null; state.wallet = null; state.lastTrace = null; mode = null;
  if (location.hash) location.hash = ''; else route();
}
window.addEventListener('sw:signout', signOut);
setUnauthorizedHandler(() => { if (!state.user) return; auth.clear(); state.user = null; mode = null; toast('Your session ended. Please sign in again.'); route(); });

(async function boot() {
  applyTheme();
  if (auth.token) {
    try { const me = await api('/auth/me'); state.user = me.user; state.wallet = me.wallet; } catch { auth.clear(); }
  }
  route();
})();
