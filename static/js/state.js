import { api } from './api.js';

export const state = { user: null, wallet: null, prefill: null, lastTrace: null, routeCount: 0 };

/** Tiny event bus: the "Under the hood" panel listens for `trace` events from payments. */
export const bus = new EventTarget();
export function emitTrace(steps, title) {
  state.lastTrace = { steps, title, at: Date.now() };
  bus.dispatchEvent(new CustomEvent('trace', { detail: state.lastTrace }));
}

export async function refreshWallet() {
  state.wallet = await api('/wallet');
  return state.wallet;
}

/** Navigate to a route (without the leading #/). Re-renders even if we are already there. */
export function go(path) {
  const hash = '#/' + path;
  if (location.hash === hash) window.dispatchEvent(new Event('hashchange'));
  else location.hash = hash;
}
export function back(fallback = 'home') {
  if (state.routeCount > 1) history.back();
  else go(fallback);
}
