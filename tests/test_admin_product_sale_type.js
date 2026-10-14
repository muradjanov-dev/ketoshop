// Exercise the real form-loading and submit handlers without a browser dependency.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('webapp/admin.html', 'utf8');
const markup = html.split('<form class="modal" id="prodForm">')[1].split('</form>')[0];
const defaults = {};
for (const match of markup.matchAll(/<(input|select|textarea)\b([^>]*)>([\s\S]*?)(?=<\/\1>|<)/g)) {
  const name = match[2].match(/\bname="([^"]+)"/)?.[1];
  if (!name) continue;
  const value = match[2].match(/\bvalue="([^"]*)"/)?.[1];
  const select = match[1] === 'select'
    ? markup.slice(match.index).split('</select>')[0].match(/<option\b[^>]*value="([^"]*)"/)?.[1]
    : undefined;
  defaults[name] = value ?? select ?? '';
}
const form = {reset() {
  for (const [name, value] of Object.entries(defaults)) this[name] = {value};
}, addEventListener(event, handler) { this[event] = handler; }};
form.reset();
const nodes = {'#prodForm': form, '#prodImgUrl': {value: ''}, '#prodImgPrev': {},
  '#prodModalTitle': {}, '#prodModal': {classList: {add() {}}}, '#prodSaveBtn': {}};
const requests = [];
const context = vm.createContext({
  window: {}, editingProdId: null, lastCatValue: '',
  PRODUCTS: [{id: 145, name: 'Bodom uni', category: 'flour', unit: 'kg', price: 180000,
    cost_price: 120000, quantity: 10, b2b_price: 150000, b2b_only: true}],
  $: selector => nodes[selector], refreshCyrPreview() {}, closeModals() {}, toast() {},
  loadProducts: async () => {},
  api: async (url, options) => requests.push({url, body: JSON.parse(options.body)}),
});
vm.runInContext(html.match(/window\.openProdModal=function\(id\)\{[\s\S]*?^\};/m)[0], context);
vm.runInContext(html.match(/\$\('#prodForm'\)\.addEventListener\('submit',[\s\S]*?^\}\);/m)[0], context);

async function main() {
  // A missing input, failure to hydrate it, or omitted API field breaks these cases.
  context.window.openProdModal(145);
  assert.ok(form.b2b_only, 'Create/edit form must offer a sale-type choice');
  assert.equal(form.b2b_only.value, 'true', 'Existing B2B product is selected correctly');
  await form.submit({target: form, preventDefault() {}});
  assert.equal(requests.at(-1).url, '/admin/api/products/145');
  assert.equal(requests.at(-1).body.b2b_only, true);
  assert.equal(requests.at(-1).body.b2b_price, 150000);
  form.b2b_only.value = 'false';
  await form.submit({target: form, preventDefault() {}});
  assert.equal(requests.at(-1).body.b2b_only, false, 'General store is a boolean false');
  assert.equal(requests.at(-1).body.b2b_price, 150000);

  context.PRODUCTS[0].b2b_only = false;
  context.window.openProdModal(145);
  assert.equal(form.b2b_only.value, 'false', 'Existing general-store product is selected correctly');
  context.PRODUCTS[0].b2b_only = null;
  context.window.openProdModal(145);
  assert.equal(form.b2b_only.value, 'false', 'Legacy null means general store');

  context.PRODUCTS[0].b2b_only = true;
  context.window.openProdModal(145);
  context.window.openProdModal(null);
  assert.equal(form.b2b_only.value, 'false', 'New product resets a previous B2B choice');
  form.name.value = 'Yangi un'; form.price.value = '180000';
  await form.submit({target: form, preventDefault() {}});
  assert.equal(requests.at(-1).url, '/admin/api/products');
  assert.equal(requests.at(-1).body.b2b_only, false);
  form.b2b_only.value = 'true';
  await form.submit({target: form, preventDefault() {}});
  assert.equal(requests.at(-1).body.b2b_only, true, 'New B2B selection reaches the API');
  console.log('Admin sale type: edit, create, legacy default, reset, and boolean payload passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
