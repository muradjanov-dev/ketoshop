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
