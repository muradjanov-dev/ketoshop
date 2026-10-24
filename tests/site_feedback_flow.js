// Runs the Mini App's «sayt qulaymi?» block (webapp/index.html, from
// SITE_FB_KEY to "// ===== INIT =====") against a fake DOM, localStorage and
// api(), for one scenario given in argv[2]: {"due": bool, "stored": {...}}.
// Prints what happened as JSON. Driven by tests/test_site_feedback_asks.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'index.html'), 'utf8');
const start = html.indexOf("const SITE_FB_KEY");
const end = html.indexOf('// ===== INIT =====', start);
if (start < 0 || end < 0) throw new Error('site feedback block not found');
const scenario = JSON.parse(process.argv[2] || '{}');

const store = {};
if (scenario.stored) store.ketoshop_site_fb = JSON.stringify(scenario.stored);
const calls = [];
let tick = null;
const el = () => ({
  classList: { add: c => calls.push(['open', c]), remove() {}, toggle() {}, contains: () => false },
  setAttribute() {}, addEventListener() {}, focus() {}, style: {}, dataset: {}, value: '', textContent: '', disabled: false,
});
const ctx = {
  localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
  document: {
    visibilityState: 'visible',
    getElementById: () => el(),
    querySelectorAll: () => [],
    querySelector: () => null,
  },
  api: (url, opts) => { calls.push(['api', url, (opts && opts.method) || 'GET']);
                        return Promise.resolve(url.endsWith('/due') ? { due: !!scenario.due } : { ok: true }); },
  setInterval: fn => { tick = fn; return 1; }, clearInterval: () => { tick = null; },
  gx: a => a, updateBackButton() {}, showToast() {}, tg: {}, t: {}, activePage: 'home', gameState: null,
  Date, JSON, Math, Promise,
};
vm.createContext(ctx);
vm.runInContext(html.slice(start, end), ctx);
(async () => {
  for (let i = 0; i < 20 && tick; i++) tick();        // 100 s of visible time
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));
  process.stdout.write(JSON.stringify({ calls, stored: store.ketoshop_site_fb ? JSON.parse(store.ketoshop_site_fb) : null }));
})();
