import { api, auth } from '../api.js';
import { state, refreshWallet } from '../state.js';
import { html, paint, $, $$, errText } from '../ui.js';
import { icon, logo } from '../icons.js';

export function mount(host, { onAuthed }) {
  let mode = 'login';
  document.title = 'Smart Wallet';
  const draw = () => {
    paint(host, html`
      <div class="auth-frame">
        <div class="auth-hero"><div class="wmark">${logo()}Smart Wallet</div><h1>Pay anyone. Trust every rupee.</h1><p>An AI shield checks each payment before it leaves your wallet.</p></div>
        <div class="auth-card">
          <div class="seg" role="group" aria-label="Sign in or create account">
            <button type="button" data-mode="login" aria-pressed="${String(mode === 'login')}">Sign in</button>
            <button type="button" data-mode="register" aria-pressed="${String(mode === 'register')}">Create account</button>
          </div>
          <form id="auth-form" novalidate>
            ${mode === 'register' ? html`<div class="field"><label for="full_name">Full name</label><input id="full_name" autocomplete="name"></div>` : ''}
            <div class="field"><label for="email">Email</label><input id="email" type="email" autocomplete="email"></div>
            ${mode === 'register' ? html`<div class="field"><label for="phone">Mobile number <span class="muted">(optional)</span></label><input id="phone" inputmode="numeric" maxlength="10" autocomplete="tel-national"></div>` : ''}
            <div class="field"><label for="password">Password</label><input id="password" type="password" autocomplete="${mode === 'login' ? 'current-password' : 'new-password'}">${mode === 'register' ? html`<span class="hint">At least 8 characters, with letters and numbers.</span>` : ''}</div>
            <div id="auth-err" class="err" role="alert"></div>
            <button class="btn block" id="auth-go" type="submit">${mode === 'login' ? 'Sign in' : 'Create my wallet'}</button>
          </form>
          <div class="demo-row">
            <button class="btn soft block" type="button" data-demo="aarav@wallet.test|Demo@1234">Try the demo as Aarav (student)</button>
            <button class="btn ghost block" type="button" data-demo="admin@wallet.test|Admin@123">Demo as admin</button>
          </div>
        </div>
      </div>`);
    wire();
  };
  async function submit(body) {
    const err = $('#auth-err', host), btn = $('#auth-go', host);
    btn.disabled = true; err.textContent = '';
    try {
      const data = await api('/auth/' + (body.full_name !== undefined ? 'register' : 'login'), { method: 'POST', body });
      auth.set(data.token); state.user = data.user; await refreshWallet(); onAuthed();
    } catch (ex) { err.textContent = errText(ex); btn.disabled = false; }
  }
  const wire = () => {
    $$('[data-mode]', host).forEach((b) => b.addEventListener('click', () => { mode = b.dataset.mode; draw(); }));
    $$('[data-demo]', host).forEach((b) => b.addEventListener('click', () => { const [email, password] = b.dataset.demo.split('|'); mode = 'login'; if (!$('#auth-form', host)) draw(); submit({ email, password }); }));
    $('#auth-form', host).addEventListener('submit', (e) => {
      e.preventDefault();
      const v = (id) => ($('#' + id, host) ? $('#' + id, host).value.trim() : '');
      const body = mode === 'login' ? { email: v('email'), password: $('#password', host).value }
        : { full_name: v('full_name'), email: v('email'), phone: v('phone'), password: $('#password', host).value };
      if (!body.email || !body.password) { $('#auth-err', host).textContent = 'Enter your email and password.'; return; }
      submit(body);
    });
  };
  draw();
}
