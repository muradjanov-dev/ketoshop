// Runs webapp/nav.html's script (the courier panel's bridge into the Yandex
// apps) with a fake browser for Android, iOS and a computer, and prints where
// it sent the page as JSON. Driven by tests/test_nav_bridge.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'nav.html'), 'utf8');
const script = html.slice(html.lastIndexOf('<script>') + 8, html.lastIndexOf('</script>'));

function run(ua, search, { hide = false } = {}) {
  const els = {};
  const el = id => els[id] || (els[id] = { id, hidden: false, href: '#', textContent: '', className: '' });
  ['ic', 'ttl', 'msg', 'maps', 'navi', 'inst', 'web'].forEach(el);
  els.inst.hidden = true;
  const nav = { replaced: null, assigned: [] };
  const timers = [];
  const listeners = {};
  const location = {
    origin: 'https://keto.test', pathname: '/nav', search,
    replace(u) { nav.replaced = u; },
  };
  Object.defineProperty(location, 'href', { set(u) { nav.assigned.push(u); }, get() { return ''; } });
  const document = {
    hidden: false,
    getElementById: el,
    addEventListener: (t, fn) => { listeners[t] = fn; },
  };
  const ctx = {
    URLSearchParams, location, document, navigator: { userAgent: ua },
    setTimeout: (fn, ms) => timers.push([ms, fn]), window: {},
    encodeURIComponent, parseInt, isFinite, Math,
  };
  vm.createContext(ctx);
  vm.runInContext(script, ctx);
  if (hide) { document.hidden = true; listeners.visibilitychange && listeners.visibilitychange(); }
  timers.sort((a, b) => a[0] - b[0]).forEach(([, fn]) => fn());
  const view = {};
  for (const [id, e] of Object.entries(els)) view[id] = { hidden: e.hidden, href: e.href, text: e.textContent, cls: e.className };
  return { nav, view, state: ctx.window.__nav || null };
}

const ANDROID = 'Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 Chrome/129.0 Mobile Safari/537.36';
const IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148';
const PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36';
const P = '?p=41.311,69.279~41.3264,69.2347~41.299,69.24';

process.stdout.write(JSON.stringify({
  android1: run(ANDROID, P),
  android2: run(ANDROID, P + '&s=2'),
  android3: run(ANDROID, P + '&s=3'),
  iosStay: run(IOS, P),
  iosLeft: run(IOS, P, { hide: true }),
  pc: run(PC, P),
  empty: run(ANDROID, '?p=abc~1000,5'),
  single: run(ANDROID, '?p=41.311,69.279'),
  origin: run(ANDROID, P + '&from=41.35,69.3'),
  originFallback: run(ANDROID, P + '&from=41.35,69.3&s=2'),
  many: run(ANDROID, '?p=' + Array.from({length: 30}, (_, i) => (41 + i / 1000) + ',69.2').join('~')),
}));
