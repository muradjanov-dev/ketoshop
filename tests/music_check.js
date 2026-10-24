// Runs the Mini App's Birdsong module (birds + classical music, webapp/index.html)
// against a fake Web Audio API and DOM, drives it through a scenario and prints
// what it did as JSON. Driven by tests/test_site_music.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'index.html'), 'utf8');
const start = html.indexOf('const Birdsong = (() => {');
const end = html.indexOf('})();', html.indexOf('return { start, sync, sing', start)) + 5;
if (start < 0 || end < 5) throw new Error('Birdsong module not found');

let now = 0;
const notes = [];                       // [time, frequency] of every triangle (piano) note started
const param = () => ({ value: 0, setValueAtTime() {}, linearRampToValueAtTime(v) { this.value = v; },
                       exponentialRampToValueAtTime() {}, cancelScheduledValues() {} });
const node = extra => Object.assign({ connect() {}, disconnect() {} }, extra);
class FakeAudioContext {
  constructor() { this.state = 'running'; this.sampleRate = 8000; this.destination = node(); }
  get currentTime() { return now; }
  resume() { this.state = 'running'; return Promise.resolve(); }
  suspend() { this.state = 'suspended'; return Promise.resolve(); }
  createGain() { return node({ gain: param() }); }
  createBiquadFilter() { return node({ type: '', frequency: param() }); }
  createDelay() { return node({ delayTime: param() }); }
  createConvolver() { return node({ buffer: null }); }
  createStereoPanner() { return node({ pan: param() }); }
  createBuffer(ch, len) { return { getChannelData: () => new Float32Array(len) }; }
  createOscillator() {
    const o = node({ type: 'sine', frequency: param(), stop() {} });
    o.start = t => { if (o.type === 'triangle') notes.push([t, o.frequency.value]); };
    return o;
  }
}
const store = {};
const toasts = [];
const listeners = {};
let tick = null;
const btn = { style: {}, classList: { toggle() {} }, setAttribute() {} };
const ctx = {
  window: { AudioContext: FakeAudioContext },
  document: {
    hidden: false,
    createElement: () => btn,
    body: { appendChild() {} },
    addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener() {},
    querySelector: () => null,
  },
  localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  activePage: 'home', t: { birdsOn: 'ON', birdsOff: 'OFF' },
  showToast: msg => toasts.push(msg), gx: (uz) => uz,
  setTimeout: () => 0, clearTimeout() {}, setInterval: fn => { tick = fn; return 1; },
  Math, Date, Object, Promise, parseInt, String, Float32Array,
};
vm.createContext(ctx);
vm.runInContext(html.slice(start, end) + '\nglobalThis.Birdsong = Birdsong;', ctx);
const B = ctx.Birdsong;
const advance = (sec) => { for (let s = 0; s < sec; s += 0.15) { now += 0.15; if (tick) tick(); } };
const out = {};

B.admin();                              // no night rule, so the test doesn't depend on the clock
B.start();
listeners.click.forEach(fn => fn());    // the first tap unlocks sound
advance(10);
out.afterTenSeconds = notes.length;
out.firstPiece = store.ketoshop_music_piece;
out.notesInOrder = notes.every((n, i) => i === 0 || n[0] >= notes[i - 1][0] - 1e-9);
out.lowest = Math.min(...notes.map(n => n[1]));
out.highest = Math.max(...notes.map(n => n[1]));

ctx.activePage = 'checkout';
advance(1);
const atCheckout = notes.length;
advance(5);
out.silentAtCheckout = notes.length === atCheckout;
ctx.activePage = 'catalog';
advance(3);
out.backAfterCheckout = notes.length > atCheckout;

btn.onclick();                          // off
const off = notes.length;
advance(5);
out.silentWhenOff = notes.length - off <= 0;
out.offToast = toasts[toasts.length - 1];
btn.onclick();                          // on again → the next piece
out.pieceAfterToggle = store.ketoshop_music_piece;
out.onToast = toasts[toasts.length - 1];

const before = store.ketoshop_music_piece;
advance(140);                           // the Canon runs about 68 s, then the next piece starts
out.autoAdvanced = store.ketoshop_music_piece !== before;
out.pieceAfterWaiting = store.ketoshop_music_piece;
out.total = notes.length;
process.stdout.write(JSON.stringify(out));
