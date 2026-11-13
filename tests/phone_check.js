// Runs the Mini App's phone rule (normalizeUzPhone, uzPhoneProblem,
// formatUzPhone) and showCheckoutFieldError (from webapp/index.html) on the
// numbers given as a JSON array in argv[2], against a tiny fake DOM, and
// prints the results as JSON. Driven by tests/test_phone_utils.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'index.html'), 'utf8');
const grab = name => {
  const start = html.indexOf('function ' + name + '(');
  if (start < 0) throw new Error(name + ' not found');
  let depth = 0;
  for (let i = html.indexOf('{', start); i < html.length; i++) {
    if (html[i] === '{') depth++;
    if (html[i] === '}' && --depth === 0) return html.slice(start, i + 1);
  }
  throw new Error(name + ' not closed');
};

const calls = [];
const box = { scrollIntoView: opts => calls.push(['scroll', 'box', opts && opts.block]) };
const field = {
  after: el => calls.push(['after', el.className, el.textContent]),
  scrollIntoView: opts => calls.push(['scroll', 'field', opts && opts.block]),
  focus: () => calls.push(['focus']),
  closest: sel => (sel === '.form-group' ? box : null),
};
const ctx = {
  document: { getElementById: id => (id === 'inp-phone' ? field : null), createElement: () => ({}) },
  showToast: (msg, isError) => calls.push(['toast', msg, isError]),
  tg: { HapticFeedback: { notificationOccurred: kind => calls.push(['haptic', kind]) } },
  setTimeout: fn => fn(), String, RegExp,
};
vm.createContext(ctx);
vm.runInContext(['uzPhoneDigits', 'normalizeUzPhone', 'uzPhoneProblem', 'formatUzPhone',
  'showCheckoutFieldError'].map(grab).join('\n'), ctx);

const numbers = JSON.parse(process.argv[2] || '[]');
const normalized = numbers.map(n => ctx.normalizeUzPhone(n));
const problems = numbers.map(n => ctx.uzPhoneProblem(n));
const formatted = numbers.map(n => ctx.formatUzPhone(n));
ctx.showCheckoutFieldError('inp-phone', 'Telefon raqamini tekshiring', true);
process.stdout.write(JSON.stringify({ normalized, problems, formatted, calls }));
