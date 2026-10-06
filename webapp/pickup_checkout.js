/* Small pure checkout policy shared by the Mini App UI and its Node behavior test. */
(function (root) {
  root.ketoshopPickupState = function (enabled, pickupSelected, hasCustomerLocation) {
    const pickup = Boolean(enabled && pickupSelected);
    return {
      offerPickup: Boolean(enabled),
      pickupSelected: pickup,
      locationRequired: !pickup,
      showCustomerLocation: !pickup,
      showDeliveryOptions: !pickup && Boolean(hasCustomerLocation),
      showPickupInstructions: pickup,
      fee: 0,
      deliveryMethod: pickup ? 'pickup' : null,
    };
  };

  root.renderPickupSuccessDetails = function (document, result) {
    const box = document.getElementById('order-success-pickup');
    if (!box) return false;
    box.replaceChildren();
    if (!result || result.delivery_method !== 'pickup') {
      box.style.display = 'none';
      return false;
    }
    const label = document.createElement('div');
    label.textContent = '🏪 Olib ketish';
    const address = document.createElement('div');
    address.textContent = '📍 ' + (result.pickup_address || '');
    const map = document.createElement('a');
    map.href = result.pickup_map_url || '';
    map.target = '_blank';
    map.rel = 'noopener';
    map.textContent = '🗺 Xaritada ochish';
    box.appendChild(label);
    box.appendChild(address);
    box.appendChild(map);
    box.style.display = 'block';
    return true;
  };
})(globalThis);
