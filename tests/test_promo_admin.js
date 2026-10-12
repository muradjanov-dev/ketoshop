const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('webapp/admin.html', 'utf8');
const context = vm.createContext({Date});
for (const name of ['promoDaysLeft', 'promoTimeLabel']) {
  const source = html.match(new RegExp(`function ${name}\\(p\\)\\{[\\s\\S]*?^\\}`, 'm'))[0];
  vm.runInContext(source, context);
}
const tomorrow = new Date(Date.now() + 86400000 * 3.5).toISOString();
assert.equal(context.promoTimeLabel({active: true, days: 7, ends_at: null}), "O'chirilguncha");
assert.equal(context.promoTimeLabel({active: true, days: 0, ends_at: tomorrow}), '4 kun qoldi');
assert.equal(context.promoTimeLabel({active: false, days: 0, ends_at: tomorrow}), "O'chirilguncha");
console.log('Promotion duration labels: running expiry and saved duration passed');
