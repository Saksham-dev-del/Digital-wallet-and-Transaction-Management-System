// Thin fetch wrapper. The session token lives in sessionStorage (cleared when the tab closes).
const KEY = 'sw_token';
export const auth = {
  get token() { try { return sessionStorage.getItem(KEY) || ''; } catch { return ''; } },
  set(t) { try { sessionStorage.setItem(KEY, t); } catch { /* private mode */ } },
  clear() { try { sessionStorage.removeItem(KEY); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(data, status) {
    super((data && data.error) || 'Request failed');
    this.status = status;
    this.code = data && data.code;
    this.data = data || {};
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

const PAYMENT_STATES = ['SUCCESS', 'PENDING_OTP', 'BLOCKED', 'FAILED'];

/** Returns the parsed JSON. Throws ApiError for errors - except payment results (BLOCKED / FAILED),
 *  which carry a `status` and are meaningful answers rather than errors. */
export async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const opts = { method, headers: { ...headers } };
  if (auth.token) opts.headers.Authorization = 'Bearer ' + auth.token;
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch('/api' + path, opts); }
  catch { throw new ApiError({ error: 'Cannot reach the server. Is it running?', code: 'network' }, 0); }
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok && !(data && PAYMENT_STATES.includes(data.status))) {
    if (res.status === 401 && data.code === 'unauthorized') onUnauthorized();   // only a dead session signs the user out
    throw new ApiError(data, res.status);
  }
  return data;
}

export async function downloadFile(path, filename) {
  const res = await fetch('/api' + path, { headers: { Authorization: 'Bearer ' + auth.token } });
  if (!res.ok) { let d = {}; try { d = await res.json(); } catch { /* */ } throw new ApiError(d, res.status); }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
