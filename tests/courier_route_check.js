// Runs the courier panel's route code (webapp/admin.html, "Marshrut") against
// a fake board and localStorage, drives it through a scenario and prints what
// it did as JSON. Driven by tests/test_courier_route.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'admin.html'), 'utf8');

function line(prefix) {
  const i = html.indexOf(prefix);
  if (i < 0) throw new Error('not found: ' + prefix);
  return html.slice(i, html.indexOf('\n', i));
}
function fn(name) {
  const i = html.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('function not found: ' + name);
  let depth = 0, j = html.indexOf('{', i);
  for (; j < html.length; j++) {
    if (html[j] === '{') depth++;
    else if (html[j] === '}' && --depth === 0) break;
  }
  return html.slice(i, j + 1);
}

const src = [
  line('const KB_COORD_PREFIX_RE='),
  line('const KB_ROUTE_KEY='),
  line('const KB_ROUTE_SKIP_METHODS='),
  'let KB_BOARD=null, KB_MAP=null, KB_ROUTE_LINE=null, KB_ROUTE_NUM=new Map(), KB_ROUTE_OPEN=true;',
  ...['kbNavUrl', 'kbMapWhere', 'kbMapPin', 'kbRouteLoad', 'kbRouteSave', 'kbRouteCandidates',
      'kbDist', 'kbRouteStops', 'kbRouteMove', 'kbRouteSkip', 'kbRouteRender'].map(fn),
  'this.api={kbNavUrl,kbRouteStops,kbRouteMove,kbRouteSkip,kbRouteRender,' +
  'setBoard:b=>{KB_BOARD=b;},num:()=>[...KB_ROUTE_NUM.entries()]};',
].join('\n');

const store = {};
const box = { hidden: true, innerHTML: '' };
const ctx = {
  localStorage: {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: k => { delete store[k]; },
  },
  $: sel => (sel === '#kbRoute' ? box : null),
  esc: s => String(s).replace(/[&<>"']/g, ch => `&#${ch.charCodeAt(0)};`),
  kbMapRender: () => {},
  getComputedStyle: () => ({ getPropertyValue: () => '#E48A3D' }),
  document: { documentElement: {} },
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const api = ctx.api;

const card = (id, status, lat, lng, extra = {}) => Object.assign(
  { id, status, latitude: lat, longitude: lng, customer_name: 'Mijoz ' + id,
    delivery_method: 'self', address: 'Ko‘cha ' + id, stage_minutes: 0 }, extra);
const board = cards => ({ columns: [
  { key: 'accepted', cards: cards.filter(c => c.status === 'confirmed') },
  { key: 'delivery', cards: cards.filter(c => ['ready', 'shipped', 'preparing'].includes(c.status)) },
] });
const ids = () => api.kbRouteStops().stops.map(x => x.c.id);
const out = {};

const A = card(1, 'ready', 41.30, 69.20, { stage_minutes: 50 });
const B = card(2, 'ready', 41.31, 69.21, { stage_minutes: 10 });
const C = card(3, 'shipped', 41.35, 69.30, { stage_minutes: 5 });
const others = [
  card(4, 'ready', 41.32, 69.22, { delivery_method: 'pickup' }),
  card(5, 'ready', null, null, { address: 'Chilonzor 5' }),
  card(6, 'confirmed', 41.33, 69.23),
  card(7, 'ready', 41.34, 69.24, { delivery_method: 'yandex_taxi' }),
  card(8, 'preparing', 41.34, 69.25),
];
api.setBoard(board([A, B, C, ...others]));
out.auto = ids();
out.single = api.kbNavUrl([[41.3, 69.2]]);

api.kbRouteMove(3, -1);
out.moved = ids();
// next poll: #1 delivered (gone), #9 new next to #2
const H = card(9, 'ready', 41.311, 69.211);
api.setBoard(board([B, C, H, ...others]));
out.afterPoll = ids();

api.kbRouteSkip(3, true);
out.skipped = ids();
out.skippedList = api.kbRouteStops().skipped.map(x => x.c.id);
api.kbRouteSkip(3, false);
out.readded = ids();

api.kbRouteRender();
out.html = box.innerHTML;
out.hidden = box.hidden;
out.num = api.num();

const many = Array.from({ length: 12 }, (_, i) => card(100 + i, 'ready', 41.2 + i / 100, 69.2));
store.ketoshop_kb_route = undefined; delete store.ketoshop_kb_route;
api.setBoard(board(many));
api.kbRouteRender();
out.legs = (box.innerHTML.match(/🧭 \d+–\d+/g) || []);
out.legLinks = (box.innerHTML.match(/rtext=~[^"&]*/g) || []).map(s => s.split('~').length - 1);

api.setBoard(board([]));
api.kbRouteRender();
out.emptyHidden = box.hidden;

process.stdout.write(JSON.stringify(out));
