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
})(globalThis);
