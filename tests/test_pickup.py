"""Pickup configuration and checkout safety behavior."""
import unittest

import pickup


class PickupConfigurationTests(unittest.TestCase):
    def test_disabled_default_does_not_expose_incomplete_shop_details(self):
        self.assertEqual(pickup.public_config(None), {
            "enabled": False, "address": "", "map_url": "", "working_hours": "", "fee": 0
        })

    def test_enabled_settings_require_address_hours_and_https_map(self):
        base = {"enabled": True, "address": "Real shop", "map_url": "https://maps.example/shop", "working_hours": "Mon-Fri"}
        self.assertIsNone(pickup.validate_settings(base))
        for field, value in (("address", ""), ("working_hours", ""), ("map_url", "http://maps.example/shop"), ("map_url", "javascript:alert(1)")):
            changed = dict(base, **{field: value})
            self.assertIn(field, pickup.validate_settings(changed))

    def test_public_settings_only_enable_when_all_details_are_valid(self):
        invalid = {"enabled": True, "address": "Real shop", "map_url": "http://bad", "working_hours": "Mon-Fri"}
        result = pickup.public_config(invalid)
        self.assertFalse(result["enabled"])
        self.assertEqual(result["fee"], 0)

    def test_pickup_checkout_ignores_customer_coordinates_and_client_fee(self):
        payload = pickup.checkout_values(
            {"delivery_method": "pickup", "address": "tampered", "latitude": 41.3,
             "longitude": 69.2, "delivery_fee": 99000},
            {"enabled": True, "address": "Real shop", "map_url": "https://maps.example/shop", "working_hours": "Mon-Fri"},
        )
        self.assertEqual(payload["address"], "Real shop")
        self.assertIsNone(payload["latitude"])
        self.assertIsNone(payload["longitude"])
        self.assertEqual(payload["fee"], 0)

    def test_disabled_pickup_is_rejected(self):
        with self.assertRaises(pickup.PickupUnavailable):
            pickup.checkout_values({"delivery_method": "pickup"}, None)


if __name__ == "__main__":
    unittest.main()
