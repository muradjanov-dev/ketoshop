// Runs the Mini App's site-analytics tracker (webapp/index.html, "SITE
// ANALYTICS") against a tiny fake DOM and prints what it would send to
// /api/track as JSON. Driven by tests/test_site_analytics.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'index.html'), 'utf8');
const start = html.indexOf('// ===== SITE ANALYTICS');
const end = html.indexOf('function trk(fn)', start);
if (start < 0 || end < 0) throw new Error('tracker block not found');
const code = html.slice(start, end) + 'globalThis.Trk = Trk;';

let now = 1000;
const listeners = {};
const modals = { 'detail-modal': false, 'recipe-modal': false, 'promo-modal': false };
const sent = [];
const doc = {
  hidden: false,
  scrollingElement: { scrollHeight: 2000, clientHeight: 800 },
  addEventListener: (t, f) => { (listeners['doc:' + t] = listeners['doc:' + t] || []).push(f); },
  getElementById: id => (id in modals ? { classList: { contains: () => modals[id] } } : null),
};
const win = { scrollY: 0, innerHeight: 800, addEventListener: (t, f) => { (listeners['win:' + t] = listeners['win:' + t] || []).push(f); } };
const ctx = {
  document: doc, window: win, tg: { platform: 'android' },
  performance: { now: () => now },
  fetch: (url, opts) => { sent.push({ url, keepalive: opts.keepalive, body: JSON.parse(opts.body) }); return Promise.resolve(); },
  apiHeaders: () => ({ Authorization: 'tma x', 'Content-Type': 'application/json' }),
  setInterval: () => 0, Date, Math, JSON, String, Set, WeakSet, isFinite,
};
vm.createContext(ctx);
vm.runInContext(code, ctx);
const T = ctx.Trk;
const fire = (key, ev) => (listeners[key] || []).forEach(f => f(ev || {}));

T.start('direct');                       // home
now += 4000;
T.page('catalog', 'all');                // 4 s on home
now += 2000;
T.cat('sweeteners');                     // 2 s on catalog:all
now += 1000;
modals['detail-modal'] = true;
T.open('product', 42, 'catalog:sweeteners');
now += 6000;
fire('doc:scroll', { target: { scrollHeight: 1000, clientHeight: 500, scrollTop: 250 } });   // 75 %
T.ev('cart_add', 'product', 42, T.from());
modals['detail-modal'] = false;
T.close('detail');                       // 6 s on the product, back to the catalog
now += 3000;
doc.hidden = true; fire('doc:visibilitychange');      // 3 s more, then hidden: flush
now += 60000;                            // hidden time is not counted
doc.hidden = false; fire('doc:visibilitychange');
now += 2000;
win.scrollY = 1200; fire('win:pagehide');

process.stdout.write(JSON.stringify(sent));
