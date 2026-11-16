import { api } from '../api.js';
import { state } from '../state.js';
import { html, paint, $, $$, money, dateTime, toast, busy, errText, plural } from '../ui.js';
import { gantt, waitForGraph } from '../charts.js';

const TABS = [['overview', 'Overview'], ['deadlock', 'Deadlock'], ['cpu', 'CPU scheduling'], ['memory', 'Memory'], ['files', 'Files and audit'], ['stress', 'Stress test']];
const concept = (text) => html`<div class="concept">${text}</div>`;
const bytes = (n) => (n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB');
const kv = (pairs) => html`<dl class="kv">${pairs.map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>`;
const ok = (b) => (b ? html`<span class="tag ok">yes</span>` : html`<span class="tag bad">no</span>`);

export async function mount(el, ctx) {
  let cleanup = null;
  const first = ctx && ctx.params && TABS.some((t) => t[0] === ctx.params[0]) ? ctx.params[0] : 'overview';
  paint(el, html`
    <section class="page">
      <div class="page-head"><div><h1>OS lab</h1><p>The operating-system ideas behind the wallet, running live. Each tab is a classic OS topic you can poke at.</p></div></div>
      <div class="subtabs" role="tablist">${TABS.map(([id, label]) => html`<button class="subtab" role="tab" data-tab="${id}" aria-selected="${String(id === first)}">${label}</button>`)}</div>
      <div id="lab"></div>
    </section>`);

  async function show(id) {
    if (cleanup) { cleanup(); cleanup = null; }
    $$('.subtab', el).forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === id)));
    const box = $('#lab', el);
    paint(box, html`<p class="muted">Loading…</p>`);
    try { cleanup = (await TAB[id](box)) || null; } catch (e) { paint(box, html`<p class="err">${errText(e)}</p>`); }
  }
  $('.subtabs', el).addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) show(b.dataset.tab); });
  await show(first);
  return () => { if (cleanup) cleanup(); };
}

// ====================================================================== overview
async function overviewTab(box) {
  const draw = async () => {
    try {
      const o = await api('/os/overview'), sy = o.system, lk = o.locks, c = o.cache, sc = o.scheduler;
      paint(box, html`${concept('Processes, threads, locks, scheduling and caching - all of this is running inside the server you are talking to right now. The page refreshes every 3 seconds.')}
        <div class="grid2">
          <div><h2>Process and threads</h2>${kv([['Process ID', sy.pid], ['Python', sy.python], ['Platform', sy.platform], ['CPU cores', sy.cpu_count], ['Uptime', sy.uptime_s + ' s'],
            ['Peak memory', sy.peak_memory_mb == null ? 'n/a on this OS' : sy.peak_memory_mb + ' MB'], ['CPU time used', sy.cpu_time_s == null ? 'n/a' : sy.cpu_time_s + ' s'],
            ['Load average', sy.load_average ? sy.load_average.join(' / ') : 'n/a on this OS'], ['Open files', sy.open_file_descriptors ?? 'n/a']])}
            <h3 style="margin-top:14px">${plural(sy.threads.length, 'thread', 'threads')} alive</h3>
            <div class="chips">${sy.threads.map((t) => html`<span class="tag">${t.name}${t.daemon ? ' (daemon)' : ''}</span>`)}</div></div>
          <div><h2>Wallet locks (mutual exclusion)</h2>${kv([['Lock type', lk.mode], ['Wallets locked so far', lk.locks_known], ['Currently held', lk.held.length ? lk.held.map((h) => `wallet ${h.resource} by ${h.holder}`).join(', ') : 'none'],
            ['Waiting', lk.waiting.length ? lk.waiting.map((w) => `${w.thread} for wallet ${w.resource}`).join(', ') : 'none'], ['Acquired', lk.stats.acquired || 0], ['Had to wait', lk.stats.contended || 0],
            ['Timeouts', lk.stats.timeouts || 0], ['Deadlocks resolved', lk.stats.deadlocks_resolved || 0], ['Redis connected', o.redis ? 'yes' : 'no (in-memory fallback)']])}</div>
        </div>
        <div class="grid2 section">
          <div><h2>Balance cache (memory management)</h2>${kv([['Kind', c.kind], ['Entries', c.size == null ? 'n/a' : c.capacity ? `${c.size} of ${c.capacity} frames` : c.size], ['Hits / misses', `${c.hits} / ${c.misses}`],
            ['Hit ratio', c.hit_ratio == null ? 'no reads yet' : Math.round(c.hit_ratio * 100) + '%'], ['LRU evictions', c.evictions ?? 'n/a'], ['Oldest to newest', c.keys_lru_to_mru ? (c.keys_lru_to_mru.join(', ') || 'empty') : 'n/a']])}</div>
          <div><h2>Payment scheduler (process scheduling)</h2>${kv([['Running', sc.running ? 'yes' : 'no'], ['Worker threads', sc.workers], ['Checks for due payments', 'every ' + sc.poll_seconds + ' s'], ['In the queue', sc.queue_length],
            ['Enqueued / done / failed', `${sc.stats.enqueued || 0} / ${sc.stats.succeeded || 0} / ${sc.stats.failed || 0}`], ['Average wait in queue', sc.avg_queue_wait_ms == null ? 'n/a' : sc.avg_queue_wait_ms + ' ms'],
            ['Jobs per worker', Object.keys(sc.per_worker).length ? Object.entries(sc.per_worker).map(([k, v]) => `${k}: ${v}`).join(', ') : 'none yet']])}<p class="hint">${sc.policy}</p></div>
        </div>`);
    } catch (e) { paint(box, html`<p class="err">${errText(e)}</p>`); }
  };
  await draw();
  const t = setInterval(draw, 3000);
  return () => clearInterval(t);
}

// ====================================================================== deadlock
function deadlockTab(box) {
  paint(box, html`${concept('A deadlock needs four things: mutual exclusion, hold-and-wait, no pre-emption and a circular wait. Two transfers that lock the same two wallets in opposite order create a circular wait. Prevention: always lock in ascending wallet id. Detection and recovery: find the cycle in the wait-for graph and abort one victim.')}
    <div class="flex"><button class="btn danger" data-mode="naive">Run: lock in request order</button><button class="btn" data-mode="ordered">Run: lock in ascending order</button></div>
    <p class="hint">Transfer A sends wallet 1 to wallet 2 while transfer B sends wallet 2 to wallet 1, at the same moment.</p><div id="dl" class="section"></div>`);
  box.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-mode]');
    if (!b) return;
    await busy(b, async () => {
      paint($('#dl', box), html`<p class="muted">Running two transfers…</p>`);
      try {
        const r = await api('/os/deadlock', { method: 'POST', body: { mode: b.dataset.mode } });
        paint($('#dl', box), html`
          <div class="flex"><span class="stamp ${r.deadlock_detected ? 'bad' : 'good'}">${r.deadlock_detected ? 'Deadlock detected' : 'No deadlock'}</span><span class="mono small">${r.total_ms} ms</span></div>
          <p>${r.outcome}</p>
          ${r.cycle ? html`<h3>Wait-for graph at the moment of detection</h3>${waitForGraph(r.cycle)}<p class="hint">An arrow means "is waiting for a lock held by". A cycle means nobody can ever continue.</p>` : ''}
          <h3 style="margin-top:14px">What happened, step by step</h3>
          <div class="scroll"><table class="tbl timeline"><thead><tr><th>Time</th><th>Who</th><th>What</th></tr></thead><tbody>${r.events.map((ev) => html`<tr><td>${ev.t_ms} ms</td><td>${ev.thread}</td><td class="k-${ev.kind}">${ev.text}</td></tr>`)}</tbody></table></div>`);
      } catch (ex) { paint($('#dl', box), html`<p class="err">${errText(ex)}</p>`); }
    });
  });
}

// ====================================================================== cpu scheduling
const DEFAULT_JOBS = [{ pid: 'P1', arrival: 0, burst: 5, priority: 2 }, { pid: 'P2', arrival: 1, burst: 3, priority: 1 },
  { pid: 'P3', arrival: 2, burst: 8, priority: 3 }, { pid: 'P4', arrival: 3, burst: 6, priority: 2 }];
const POLICY_NAMES = { FCFS: 'First-Come First-Served', SJF: 'Shortest Job First', SRTF: 'Shortest Remaining Time', PRIORITY: 'Priority', RR: 'Round Robin' };

function cpuTab(box) {
  let jobs = DEFAULT_JOBS.map((j) => ({ ...j }));
  const drawJobs = () => paint($('#jobs', box), html`<table class="tbl jobs"><thead><tr><th>Payment job</th><th>Arrives at</th><th>Burst (run time)</th><th>Priority (1 = first)</th><th></th></tr></thead><tbody>
    ${jobs.map((j, i) => html`<tr><td><input class="pid" data-i="${i}" data-f="pid" value="${j.pid}" aria-label="Job name"></td><td><input type="number" min="0" max="100" data-i="${i}" data-f="arrival" value="${j.arrival}" aria-label="Arrival"></td>
    <td><input type="number" min="1" max="50" data-i="${i}" data-f="burst" value="${j.burst}" aria-label="Burst"></td><td><input type="number" min="1" max="9" data-i="${i}" data-f="priority" value="${j.priority}" aria-label="Priority"></td>
    <td>${jobs.length > 1 ? html`<button class="btn small ghost" data-del="${i}" aria-label="Remove job">Remove</button>` : ''}</td></tr>`)}</tbody></table>`);
  paint(box, html`${concept('The CPU scheduler decides which job runs next. Here the "jobs" are payment transactions. Change the numbers, pick a policy and compare the average waiting time - the policy with the lowest waiting time is best for response.')}
    <div id="jobs" class="scroll"></div>
    <div class="flex" style="margin:10px 0 14px"><button class="btn small ghost" id="add">Add job</button>
      <label for="policy" class="small">Policy</label><select id="policy" style="width:auto">${Object.entries(POLICY_NAMES).map(([k, v]) => html`<option value="${k}">${v}</option>`)}</select>
      <label for="q" class="small">Time slice</label><input id="q" type="number" min="1" max="20" value="2" style="width:72px" aria-label="Time slice for Round Robin">
      <button class="btn" id="run">Run</button><button class="btn ghost" id="cmp">Compare all policies</button></div>
    <div id="cpu-out"></div>`);
  drawJobs();
  const read = () => ({ jobs: jobs.map((j) => ({ ...j, arrival: Number(j.arrival), burst: Number(j.burst), priority: Number(j.priority) })), policy: $('#policy', box).value, quantum: Number($('#q', box).value) });
  box.addEventListener('input', (e) => { const i = e.target.dataset.i; if (i !== undefined) jobs[Number(i)][e.target.dataset.f] = e.target.value; });
  box.addEventListener('click', async (e) => {
    if (e.target.id === 'add') { if (jobs.length < 8) { jobs.push({ pid: 'P' + (jobs.length + 1), arrival: 0, burst: 4, priority: 3 }); drawJobs(); } else toast('Up to 8 jobs in this lab.'); }
    const del = e.target.closest('[data-del]');
    if (del) { jobs.splice(Number(del.dataset.del), 1); drawJobs(); }
    if (e.target.id === 'run') await busy(e.target, async () => {
      try {
        const r = await api('/os/cpu', { method: 'POST', body: read() });
        const order = r.processes.map((p) => p.pid);
        paint($('#cpu-out', box), html`<h3>${r.policy_name}${r.quantum ? ' (time slice ' + r.quantum + ')' : ''}</h3>${gantt(r.gantt, r.total_time, order)}
          <div class="scroll"><table class="tbl"><thead><tr><th>Job</th><th class="num">Arrival</th><th class="num">Burst</th><th class="num">Priority</th><th class="num">Finished</th><th class="num">Turnaround</th><th class="num">Waiting</th><th class="num">Response</th></tr></thead><tbody>
          ${r.processes.map((p) => html`<tr><td>${p.pid}</td><td class="num mono">${p.arrival}</td><td class="num mono">${p.burst}</td><td class="num mono">${p.priority}</td><td class="num mono">${p.completion}</td><td class="num mono">${p.turnaround}</td><td class="num mono">${p.waiting}</td><td class="num mono">${p.response}</td></tr>`)}</tbody></table></div>
          <p>Average waiting <b class="mono">${r.avg_waiting}</b>, turnaround <b class="mono">${r.avg_turnaround}</b>, response <b class="mono">${r.avg_response}</b>. CPU busy ${r.cpu_utilization}% of the time, ${plural(r.context_switches, 'context switch', 'context switches')}.</p>
          <p class="hint">Waiting = turnaround - burst. Turnaround = finish - arrival. Response = first run - arrival.</p>`);
      } catch (ex) { paint($('#cpu-out', box), html`<p class="err">${errText(ex)}</p>`); }
    });
    if (e.target.id === 'cmp') await busy(e.target, async () => {
      try {
        const base = read(), rows = [];
        for (const p of Object.keys(POLICY_NAMES)) rows.push(await api('/os/cpu', { method: 'POST', body: { ...base, policy: p } }));
        const best = Math.min(...rows.map((r) => r.avg_waiting));
        paint($('#cpu-out', box), html`<h3>Same jobs, every policy</h3><table class="tbl"><thead><tr><th>Policy</th><th class="num">Avg waiting</th><th class="num">Avg turnaround</th><th class="num">Avg response</th><th class="num">Context switches</th></tr></thead><tbody>
          ${rows.map((r) => html`<tr><td>${r.policy_name} ${r.avg_waiting === best ? html`<span class="tag ok">lowest waiting</span>` : ''}</td><td class="num mono">${r.avg_waiting}</td><td class="num mono">${r.avg_turnaround}</td><td class="num mono">${r.avg_response}</td><td class="num mono">${r.context_switches}</td></tr>`)}</tbody></table>`);
      } catch (ex) { paint($('#cpu-out', box), html`<p class="err">${errText(ex)}</p>`); }
    });
  });
}

// ====================================================================== memory
const framesTable = (name, r) => html`<h3 style="margin-top:16px">${name}: ${plural(r.faults, 'fault', 'faults')}, ${plural(r.hits, 'hit', 'hits')}</h3>
  <div class="scroll"><table class="frames"><tr><th>Page</th>${r.steps.map((s) => html`<th>${s.ref}</th>`)}</tr>
  ${Array.from({ length: r.frames }, (_, f) => html`<tr><th>F${f + 1}</th>${r.steps.map((s) => html`<td class="${s.fault ? 'fault' : 'hit'}">${s.frames[f] ?? ''}</td>`)}</tr>`)}
  <tr><th>Fault</th>${r.steps.map((s) => html`<td class="${s.fault ? 'fault' : 'hit'}">${s.fault ? 'F' : ''}</td>`)}</tr></table></div>`;

function memoryTab(box) {
  paint(box, html`${concept('When all frames are full, a page-replacement algorithm chooses a victim. The wallet balance cache uses LRU for exactly this reason. FIFO can even get worse with more frames (Belady\'s anomaly) - try the preset.')}
    <div class="grid2"><div class="field"><label for="refs">Page reference string</label><input id="refs" value="7 0 1 2 0 3 0 4 2 3 0 3 2 1 2 0 1 7 0 1"></div>
    <div class="field"><label for="frames">Frames</label><input id="frames" type="number" min="1" max="8" value="3"></div></div>
    <div class="flex"><button class="btn" id="run">Run FIFO, LRU and Optimal</button><button class="btn ghost" id="belady">Show Belady's anomaly</button></div>
    <div id="mem-out" class="section"></div>
    <div class="section"><h2>The wallet's own balance cache</h2><div id="cache"></div></div>`);
  const out = $('#mem-out', box);
  const run = async (refs, frames) => api('/os/paging', { method: 'POST', body: { refs, frames } });
  box.addEventListener('click', async (e) => {
    if (e.target.id === 'run') await busy(e.target, async () => {
      try {
        const { results } = await run($('#refs', box).value, Number($('#frames', box).value));
        paint(out, html`<table class="tbl" style="max-width:420px"><thead><tr><th>Algorithm</th><th class="num">Page faults</th><th class="num">Hits</th></tr></thead><tbody>${Object.entries(results).map(([k, r]) => html`<tr><td>${{ FIFO: 'FIFO', LRU: 'LRU', OPT: 'Optimal' }[k]}</td><td class="num mono">${r.faults}</td><td class="num mono">${r.hits}</td></tr>`)}</tbody></table>
          ${framesTable('FIFO', results.FIFO)}${framesTable('LRU', results.LRU)}${framesTable('Optimal', results.OPT)}`);
      } catch (ex) { paint(out, html`<p class="err">${errText(ex)}</p>`); }
    });
    if (e.target.id === 'belady') await busy(e.target, async () => {
      try {
        const refs = '1 2 3 4 1 2 5 1 2 3 4 5';
        $('#refs', box).value = refs;
        const three = await run(refs, 3), four = await run(refs, 4);
        paint(out, html`<p>With the reference string <span class="mono">${refs}</span>, FIFO has <b>${three.results.FIFO.faults} faults with 3 frames</b> but <b>${four.results.FIFO.faults} faults with 4 frames</b>. More memory made it worse. LRU improves from ${three.results.LRU.faults} to ${four.results.LRU.faults} faults, as you would expect.</p>
          ${framesTable('FIFO with 3 frames', three.results.FIFO)}${framesTable('FIFO with 4 frames', four.results.FIFO)}`);
      } catch (ex) { paint(out, html`<p class="err">${errText(ex)}</p>`); }
    });
    if (e.target.id === 'flush') await busy(e.target, async () => { try { await api('/os/cache/flush', { method: 'POST' }); toast('Cache flushed. The next balance read will be a miss.', 'good'); await loadCache(); } catch (ex) { toast(errText(ex), 'bad'); } });
  });
  async function loadCache() {
    try {
      const o = await api('/os/overview'), c = o.cache;
      paint($('#cache', box), html`${kv([['Kind', c.kind], ['Entries', c.capacity ? `${c.size} of ${c.capacity} frames` : (c.size ?? 'n/a')], ['Hits / misses', `${c.hits} / ${c.misses}`], ['Hit ratio', c.hit_ratio == null ? 'no reads yet' : Math.round(c.hit_ratio * 100) + '%'], ['Evictions', c.evictions ?? 'n/a']])}
        <p class="hint">Reads go to the cache first (a hit); a miss reads SQLite and fills the cache. Every payment invalidates the two wallets it touched.</p>
        ${state.user.role === 'admin' ? html`<button class="btn small ghost" id="flush">Flush cache</button>` : ''}`);
    } catch (ex) { paint($('#cache', box), html`<p class="err">${errText(ex)}</p>`); }
  }
  loadCache();
}

// ====================================================================== files + audit
async function filesTab(box) {
  const isAdmin = state.user.role === 'admin';
  const draw = async () => {
    const parts = [concept('The audit log is an append-only file: writes are sequential, fsync() forces them to disk, and every record carries the hash of the one before it, so editing or deleting any line breaks the chain. Backups use the database\'s online-backup API. File details come from os.stat().')];
    if (!isAdmin) {
      const v = await api('/os/audit/verify');
      paint(box, html`${parts}<h2>Audit log integrity</h2><p><span class="stamp ${v.ok ? 'good' : 'bad'}">${v.ok ? 'Chain intact' : 'Chain broken'}</span> ${plural(v.entries, 'record', 'records')} checked.</p><p class="hint">Sign in as the admin account to see the files, backups and the tamper demo.</p>`);
      return;
    }
    const f = await api('/os/files'), v = f.audit;
    paint(box, html`${parts}
      <div class="grid2"><div><h2>Files in the data folder</h2><table class="tbl"><thead><tr><th>Name</th><th class="num">Size</th><th>Permissions</th><th class="num">Inode</th></tr></thead><tbody>${f.data_files.map((x) => html`<tr><td>${x.name}</td><td class="num mono">${bytes(x.size_bytes)}</td><td class="mono">${x.permissions}</td><td class="num mono">${x.inode}</td></tr>`)}</tbody></table>
        <p class="hint">The -wal and -shm files are SQLite's write-ahead log: changes are appended there first, like a file-system journal.</p></div>
      <div><h2>Backups</h2><button class="btn small" id="backup">Create backup now</button>${f.backups.length ? html`<table class="tbl" style="margin-top:10px"><thead><tr><th>File</th><th class="num">Size</th><th>Taken</th></tr></thead><tbody>${f.backups.map((x) => html`<tr><td class="small">${x.name}</td><td class="num mono">${bytes(x.size_bytes)}</td><td class="small">${dateTime(x.modified)}</td></tr>`)}</tbody></table>` : html`<p class="muted">No backups yet.</p>`}</div></div>
      <div class="section"><h2>Audit log</h2><p><span class="stamp ${v.ok ? 'good' : 'bad'}">${v.ok ? 'Chain intact' : 'Chain broken at line ' + v.bad_line}</span> ${plural(v.entries, 'record', 'records')}${v.head ? html`, head hash <span class="mono small">${v.head.slice(0, 16)}…</span>` : ''}</p>
        <div class="flex"><button class="btn small ghost" id="verify">Verify again</button><button class="btn small ghost" id="tamper">Tamper demo</button></div><div id="tamper-out"></div>
        <h3 style="margin-top:14px">Latest records</h3><pre class="log">${f.audit_tail.map((r) => `#${r.seq}  ${r.ts}  ${r.event}  actor=${r.actor ?? '-'}  ${JSON.stringify(r.data)}`).join('\n')}</pre></div>`);
  };
  await draw();
  box.addEventListener('click', async (e) => {
    if (e.target.id === 'backup') await busy(e.target, async () => { try { const r = await api('/os/backup', { method: 'POST' }); toast(`Backup ${r.name} created (integrity: ${r.integrity_check}).`, 'good'); await draw(); } catch (ex) { toast(errText(ex), 'bad'); } });
    if (e.target.id === 'verify') await busy(e.target, async () => { try { await draw(); toast('Verified.', 'good'); } catch (ex) { toast(errText(ex), 'bad'); } });
    if (e.target.id === 'tamper') await busy(e.target, async () => {
      try {
        const r = await api('/os/audit/tamper-demo', { method: 'POST' });
        paint($('#tamper-out', box), r.edited_line ? html`<div class="warnbox" style="margin-top:10px">An attacker edits record <b>#${r.edited_line}</b> in a <i>copy</i> of the log (your real log is untouched). Verification of the copy: <b>${r.caught ? 'caught' : 'missed'}</b> - ${r.verification_of_copy.reason || 'ok'} (line ${r.verification_of_copy.bad_line}).</div>` : html`<p class="muted">${r.reason}</p>`);
      } catch (ex) { toast(errText(ex), 'bad'); }
    });
  });
}

// ====================================================================== stress test
function stressTab(box) {
  paint(box, html`${concept('Many threads move money between a few wallets in a throw-away database. If the locking and transactions are right, the total money never changes and every wallet equals the sum of its ledger. Try "request order" to watch the deadlock detector earn its keep.')}
    <div class="grid3"><div class="field"><label for="th">Threads</label><input id="th" type="number" min="2" max="16" value="8"></div>
      <div class="field"><label for="ops">Transfers per thread</label><input id="ops" type="number" min="1" max="100" value="40"></div>
      <div class="field"><label for="wl">Wallets</label><input id="wl" type="number" min="2" max="10" value="6"></div></div>
    <div class="field" style="max-width:360px"><label for="ord">Lock order</label><select id="ord"><option value="1">Ascending wallet id (safe)</option><option value="0">Request order (deadlock-prone)</option></select></div>
    <button class="btn" id="go">Run stress test</button><div id="st-out" class="section"></div>`);
  $('#go', box).addEventListener('click', (e) => busy(e.target, async () => {
    const out = $('#st-out', box);
    paint(out, html`<p class="muted">Running…</p>`);
    try {
      const r = await api('/os/stress', { method: 'POST', body: { threads: Number($('#th', box).value), ops: Number($('#ops', box).value), wallets: Number($('#wl', box).value), ordered: $('#ord', box).value === '1' } });
      const c = r.counters;
      paint(out, html`<p>${plural(r.threads, 'thread', 'threads')} x ${r.ops_per_thread} transfers over ${plural(r.wallets, 'wallet', 'wallets')}. Locks taken in <b>${r.lock_order}</b>.</p>
        <div class="result-cards">
          <div class="rc"><b>${r.committed}/${r.attempted}</b><span>transfers committed</span></div>
          <div class="rc ${r.money_conserved ? 'good' : 'bad'}"><b>${r.money_conserved ? 'yes' : 'NO'}</b><span>total money unchanged (${money(r.money_after_paise)})</span></div>
          <div class="rc ${r.ledger_consistent ? 'good' : 'bad'}"><b>${r.ledger_consistent ? 'yes' : 'NO'}</b><span>ledger entries add up</span></div>
          <div class="rc ${r.reconciliation_mismatches ? 'bad' : 'good'}"><b>${r.reconciliation_mismatches}</b><span>wallets not matching ledger</span></div>
          <div class="rc"><b>${r.deadlocks_resolved}</b><span>deadlocks detected and broken</span></div>
          <div class="rc"><b>${r.transfers_per_second ?? '-'}</b><span>transfers per second (${r.elapsed_s} s)</span></div></div>
        <p class="small muted">Other outcomes: ${Object.entries(c).filter(([k]) => k !== 'committed').map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ') || 'none'}. Lock stats: acquired ${r.lock_stats.acquired || 0}, had to wait ${r.lock_stats.contended || 0}.</p>`);
    } catch (ex) { paint(out, html`<p class="err">${errText(ex)}</p>`); }
  }));
}

const TAB = { overview: overviewTab, deadlock: deadlockTab, cpu: cpuTab, memory: memoryTab, files: filesTab, stress: stressTab };
