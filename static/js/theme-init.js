// Runs before first paint so the page never flashes the wrong theme.
(function () {
  try {
    var pref = localStorage.getItem('sw_theme') || 'system';
    var dark = pref === 'dark' || (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) { /* storage blocked: stay light */ }
})();
