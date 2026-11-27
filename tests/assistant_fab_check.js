// «Yordamchi» button: only on home and catalog (owner, 2026-11-17: "o'yinlarda va ko'p
// joyda chiqib xalaqit beryapti"), and it stays put while scrolling (owner, 2026-11-27:
// "pastga tushganda yo'q bo'lib tepaga chiqqanda yana paydo bo'lmasin ... qotib tursin").
// Runs the real Assistant module from webapp/index.html against a tiny DOM stub.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const html = fs.readFileSync('webapp/index.html', 'utf8');
const start = html.indexOf('const Assistant = (() => {');
const end = html.indexOf('})();', start);
assert.ok(start > 0 && end > start, 'Assistant module not found in index.html');
const src = html.slice(start, end + 5).replace('const Assistant =', 'globalThis.Assistant =');

function el() {
  const cls = new Set();
  return {
    classList: {
      add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c),
      toggle: (c, on) => { (on === undefined ? !cls.has(c) : on) ? cls.add(c) : cls.delete(c); },
    },
    style: {}, textContent: '', innerHTML: '', value: '',
    setAttribute() {}, addEventListener() {}, appendChild() {}, remove() {},
  };
}
const els = {};
let scrollListener = null;
const ctx = {
  activePage: 'catalog',
  tg: { initDataUnsafe: { user: { id: 1 } } },
  gx: (uz) => uz,
  _isModalOpen: id => els[id] ? els[id].classList.contains('show') : false,
  sessionStorage: { getItem: () => '1', setItem() {} },   // intro already played this launch
  setTimeout: () => 0, clearTimeout() {},
  matchMedia: () => ({ matches: false }),
  trk() {},
  document: {
    getElementById: id => (els[id] = els[id] || el()),
    querySelector: () => null,
    documentElement: { scrollTop: 0 },
  },
};
ctx.window = { scrollY: 0, addEventListener: (type, fn) => { if (type === 'scroll') scrollListener = fn; } };
vm.createContext(ctx);
vm.runInContext(src, ctx);
const A = ctx.Assistant;
const hidden = () => els['asst-fab'].classList.contains('hidden');
const scrollTo = y => { ctx.window.scrollY = y; if (scrollListener) scrollListener(); };
const go = page => { ctx.activePage = page; A.sync(); };

els['asst-fab'] = el();
els['asst-fab'].classList.add('hidden');   // the page starts it hidden
A.start();
assert.equal(hidden(), false, 'shown on the catalog');
assert.equal(scrollListener, null, 'does not react to scrolling');

for (const page of ['games', 'cart', 'checkout', 'cheque', 'order-success', 'orders', 'profile', 'fav']) {
  go(page);
  assert.equal(hidden(), true, `hidden on ${page}`);
}
go('home');
assert.equal(hidden(), false, 'shown on home');

for (const y of [40, 400, 405, 300, 900, 0, 1500]) {
  scrollTo(y);
  assert.equal(hidden(), false, `stays in view at scroll ${y}`);
}
go('catalog');
assert.equal(hidden(), false, 'shown on the catalog');
scrollTo(1200);
assert.equal(hidden(), false, 'still in view after scrolling the catalog');

go('games');
scrollTo(0);
assert.equal(hidden(), true, 'never shown in games');

console.log('assistant_fab_check: ok');
