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
  return html.slice(html.slice(i - 6, i) === 'async ' ? i - 6 : i, j + 1);
}

const src = [
  line('const KB_COORD_PREFIX_RE='),
  line('const KB_ROUTE_KEY='),
  'const KB_DELIVERY={bts:"📦 BTS"};',
  line('const KB_POS_TTL='),
  line('let KB_MY_POS='),
  "const KB_PHONE=true; let KB_VIEW='board';",
  'let KB_BOARD=null, KB_MAP=null, KB_ROUTE_LINE=null, KB_ME_MARKER=null, KB_ROUTE_NUM=new Map(), KB_ROUTE_OPEN=true;',
  ...['kbNavUrl', 'kbNavAttr', 'kbNavPins', 'kbMyPos', 'kbTgLocation', 'kbLocate', 'kbAppUrl', 'kbWidgetUrl', 'kbRouteLegs', 'kbMapWhere', 'kbMapPin',
      'kbRouteLoad', 'kbRouteSave', 'kbRouteCandidates', 'kbRouteReady', 'kbDist', 'kbRouteStops', 'kbRouteMove',
      'kbRouteSkip', 'kbRouteRender'].map(fn),
  ...(html.includes('function kbOpenRoute(') ? [fn('kbOpenRoute')] : []),
  html.slice(html.indexOf("$('#kbView').addEventListener('click'"),
             html.indexOf("$('#kbMapView').addEventListener('click'")),
  html.slice(html.indexOf("document.addEventListener('click',e=>{\n  const a=e.target"),
             html.indexOf('\nfunction kbYandex(')),
  'this.api={kbNavUrl,kbWidgetUrl,kbRouteStops,kbRouteMove,kbRouteSkip,kbRouteRender,kbRouteLoad,' +
  'kbAppUrl,kbOpenRoute,' +
  'setBoard:b=>{KB_BOARD=b;},num:()=>[...KB_ROUTE_NUM.entries()],' +
  'setPos:p=>{KB_MY_POS=p;KB_MY_POS_AT=p?Date.now():0;KB_POS_STATE=p?"ok":"off";}};',
].join('\n');

const store = {};
const box = { hidden: true, innerHTML: '' };
const listeners = {}, opened = [], views = [], notices = [];
const locationRequests = [], timers = [], popups = [], sameWindow = [];
const ctx = {
  localStorage: {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: k => { delete store[k]; },
  },
  $: sel => (sel === '#kbRoute' ? box : sel === '#kbView' ? {addEventListener: (ev, cb) => {listeners[ev] = cb;}} : null),
  location: {origin: 'https://keto.test', assign: url => sameWindow.push(url)},
  window: {Telegram:{WebApp:{initData:'fixture',openLink:()=>{}}}},
  navigator: {geolocation: {getCurrentPosition: (ok, fail) => locationRequests.push({ok, fail})}},
  setTimeout: (callback, ms) => {timers.push({callback, ms});return timers.length;},
  kbPosChanged: () => {},
  kbOpenOut: url => opened.push(url),
  kbSetView: view => views.push(view),
  toast: text => notices.push(text),
  esc: s => String(s).replace(/[&<>"']/g, ch => `&#${ch.charCodeAt(0)};`),
  kbMapRender: () => {},
  getComputedStyle: () => ({ getPropertyValue: () => '#E48A3D' }),
  document: { documentElement: {}, addEventListener: (ev, cb) => {listeners['doc:' + ev] = cb;} },
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const api = ctx.api;

const card = (id, status, lat, lng, extra = {}) => Object.assign(
  { id, status, latitude: lat, longitude: lng, customer_name: 'Mijoz ' + id,
    delivery_method: 'self', address: 'Ko‘cha ' + id, stage_minutes: 0 }, extra);
const board = cards => ({ columns: [
  { key: 'new', cards: cards.filter(c => c.status === 'pending') },
  { key: 'accepted', cards: cards.filter(c => c.status === 'confirmed') },
  { key: 'delivery', cards: cards.filter(c => ['ready', 'shipped', 'preparing'].includes(c.status)) },
  { key: 'done', cards: cards.filter(c => c.status === 'delivered') },
  { key: 'cancelled', cards: cards.filter(c => c.status === 'cancelled') },
] });
const ids = () => api.kbRouteStops().stops.map(x => x.c.id);
const out = {};

const A = card(1, 'ready', 41.30, 69.20, { stage_minutes: 50 });
const B = card(2, 'ready', 41.31, 69.21, { stage_minutes: 10 });
const C = card(3, 'shipped', 41.35, 69.30, { stage_minutes: 5 });
const others = [
  card(4, 'ready', 41.32, 69.22, { delivery_method: 'pickup' }),
  card(5, 'ready', null, null, { address: 'Chilonzor 5' }),
  card(6, 'delivered', 41.33, 69.23),
  card(7, 'ready', 40.33, 67.97, { delivery_method: 'bts' }),   // regional parcel — still a stop
  card(8, 'cancelled', 41.34, 69.25),
];
api.setBoard(board([A, B, C, ...others]));
out.auto = ids();
out.single = api.kbNavUrl([[41.3, 69.2]]);

api.kbRouteMove(3, -1);
out.moved = ids();
out.manualAfterMove = api.kbRouteLoad().manual;
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
out.offLine = box.innerHTML.includes('data-route-locate');

const many = Array.from({ length: 30 }, (_, i) => card(100 + i, 'ready', 41.2 + i / 100, 69.2));
delete store.ketoshop_kb_route;
api.setBoard(board(many));
api.kbRouteRender();
out.legs = (box.innerHTML.match(/🧭 \d+–\d+/g) || []);
out.legLinks = (box.innerHTML.match(/rtext=~[^"&]*/g) || []).map(s => s.split('~').length - 1);
out.mainRouteLinks = (box.innerHTML.match(/class="btn btn-p btn-sm"/g) || []).length;

// ready orders exist but none to drive to → the panel says why, never vanishes
api.setBoard(board([others[0], others[1]]));
api.kbRouteRender();
out.noStopHidden = box.hidden;
out.noStopHtml = box.innerHTML;

api.setBoard(board([]));
api.kbRouteRender();
out.emptyHidden = box.hidden;

// The courier's position known → the automatic order starts nearest to them,
// and every link and the Yandex widget start from there.
delete store.ketoshop_kb_route;
api.setBoard(board([A, B, C, H]));
api.setPos([41.351, 69.301]);
out.fromMe = ids();
out.navFromMe = api.kbNavUrl([[41.3, 69.2]]);
out.appFromMe = api.kbAppUrl([[41.3, 69.2], [41.31, 69.21]]);
out.widgetFromMe = api.kbWidgetUrl([[41.3, 69.2], [41.31, 69.21]]);
api.kbRouteRender();
out.posLine = box.innerHTML.includes('Yo’l hozirgi joyingizdan boshlanadi');
out.viewBtn = box.innerHTML.includes('data-route-view');
out.navAttr = (box.innerHTML.match(/data-nav="[^"]*"/) || [''])[0];
api.setPos(null);
out.widgetNoPos = api.kbWidgetUrl([[41.3, 69.2], [41.31, 69.21]]);

delete store.ketoshop_kb_route;
api.setBoard(board([
  ...['pending','confirmed','preparing','ready','shipped','delivered','cancelled']
    .map((status,i) => card(21+i,status,41.311+i/1000,69.279+i/1000)),
  card(28,'ready',999,69.2), card(29,'ready',41.3,'not-a-coordinate'),
]));
api.setPos([41.310,69.278]);
out.active = ids();
out.openedBeforeTap = opened.length;
listeners.click({target:{closest: () => ({dataset:{view:'map'}})}});
out.mapTapOpened = opened.slice();
out.mapTapViews = views.slice();
api.setBoard(board([]));
listeners.click({target:{closest: () => ({dataset:{view:'map'}})}});
out.emptyTapOpened = opened.length;
let singleTapPrevented = false;
listeners['doc:click']({target:{closest: () => ({dataset:{nav:'41.300000,69.200000'}})},
  preventDefault: () => {singleTapPrevented = true;}});
out.singleTapPrevented = singleTapPrevented;
out.singleTapOpened = opened[opened.length - 1];

(async () => {
  delete store.ketoshop_kb_route;
  api.setBoard(board([A,B,C]));
  api.setPos(null);
  const count = opened.length, requests = locationRequests.length;
  const pending = listeners.click({target:{closest: () => ({dataset:{view:'map'}})}});
  out.delayedOpenedBeforePosition = opened.length - count;
  out.delayedRequestedPosition = locationRequests.length > requests;
  if(locationRequests.length > requests)locationRequests[requests].ok({coords:{latitude:41.351,longitude:69.301}});
  await pending;
  out.delayedRoute = opened[opened.length - 1];

  // A normal browser reserves its popup during the tap, before the location promise.
  api.setPos(null);
  ctx.window = {open: () => {
    const popup = {opener: {}, document:{title:'',body:{textContent:''}},
      location:{replace:url=>{popup.url=url;}},close:()=>{popup.closed=true;}};
    popups.push(popup);return popup;
  }};
  const browserRequests = locationRequests.length;
  const browserPending = api.kbOpenRoute();
  out.reservedBeforePosition = popups.length;
  if(locationRequests.length > browserRequests)locationRequests[browserRequests].ok({coords:{latitude:41.351,longitude:69.301}});
  await browserPending;
  out.reservedRoute = popups.length ? popups[0].url : null;
  out.reservedOpener = popups.length ? popups[0].opener : 'not-reserved';

  // Unknown location has a bounded fallback, and a blocked popup uses this tab.
  api.setPos(null);
  ctx.window = {open: () => null};
  const fallbackPending = api.kbOpenRoute();
  const bound = timers.filter(timer => timer.ms <= 5000).pop();
  if(bound)bound.callback();
  await fallbackPending;
  out.boundedFallback = sameWindow.slice();

  delete store.ketoshop_kb_route;
  api.kbRouteMove(3,-1);
  const manualRequests=locationRequests.length;
  await listeners['doc:click']({target:{closest:()=>({dataset:{routeNav:''}})},preventDefault:()=>{}});
  out.manualRoute=opened[opened.length-1];
  out.manualRequestedPosition=locationRequests.length-manualRequests;
  process.stdout.write(JSON.stringify(out));
})().catch(error => {console.error(error);process.exitCode=1;});
