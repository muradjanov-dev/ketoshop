// Execute the same checkout visibility policy used by webapp/index.html.
const assert = require('node:assert/strict');
require('../webapp/pickup_checkout.js');
const state = globalThis.ketoshopPickupState;

assert.deepEqual(state(false, false, false), {
  offerPickup: false, pickupSelected: false, locationRequired: true,
  showCustomerLocation: true, showDeliveryOptions: false,
  showPickupInstructions: false, fee: 0, deliveryMethod: null,
});
assert.deepEqual(state(true, true, false), {
  offerPickup: true, pickupSelected: true, locationRequired: false,
  showCustomerLocation: false, showDeliveryOptions: false,
  showPickupInstructions: true, fee: 0, deliveryMethod: 'pickup',
});
assert.deepEqual(state(true, false, true), {
  offerPickup: true, pickupSelected: false, locationRequired: true,
  showCustomerLocation: true, showDeliveryOptions: true,
  showPickupInstructions: false, fee: 0, deliveryMethod: null,
});
console.log('pickup checkout policy: 3 behavior cases passed');

function makeDocument() {
  const success = {style: {}, children: [], replaceChildren(...nodes) { this.children = nodes; },
    appendChild(node) { this.children.push(node); }};
  return {
    success,
    getElementById(id) { return id === 'order-success-pickup' ? success : null; },
    createElement(tag) { return {tag, style: {}, children: [], appendChild(node) { this.children.push(node); }}; },
    createTextNode(text) { return {textContent: text}; },
  };
}

for (const result of [
  {delivery_method:'pickup', pickup_address:'Cash shop', pickup_map_url:'https://maps.example/cash'},
  // Represents the API response after cheque upload, using the deferred order
  // snapshot even if current settings have since changed.
  {delivery_method:'pickup', pickup_address:'Online snapshot shop', pickup_map_url:'https://maps.example/old'},
]) {
  const doc = makeDocument();
  assert.equal(globalThis.renderPickupSuccessDetails(doc, result), true);
  assert.equal(doc.success.style.display, 'block');
  assert.equal(doc.success.children[0].textContent, '🏪 Olib ketish');
  assert.equal(doc.success.children[1].textContent, '📍 ' + result.pickup_address);
  assert.equal(doc.success.children[2].tag, 'a');
  assert.equal(doc.success.children[2].href, result.pickup_map_url);
}
const regularDoc = makeDocument();
assert.equal(globalThis.renderPickupSuccessDetails(regularDoc, {delivery_method:'self'}), false);
assert.equal(regularDoc.success.style.display, 'none');
console.log('pickup success renderer: cash, deferred online snapshot, and delivery passed');
