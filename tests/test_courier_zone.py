"""Kuryer narxi — Toshkent shahri chegarasi (egasi, 2026-11-26: "faqat toshkent
shahri ichida 25000 ... shahardan tashqariga chiqqach 25000 + har 1 km uchun 3000")."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import courier_zone as z
from config import FREE_DELIVERY_FROM
from handlers.cart import delivery_fee_for


class CourierZoneTest(unittest.TestCase):
    def test_city_points_are_inside(self):
        for lat, lng in ((41.3111, 69.2797), (41.3265, 69.2346), (41.3720, 69.2895), (41.2266, 69.2219)):
            self.assertTrue(z.inside_city(lat, lng), (lat, lng))
            self.assertEqual(z.billable_km(lat, lng), 0)

    def test_outside_pays_per_started_km(self):
        self.assertEqual(z.billable_km(41.1905, 69.1381), 5)                  # Zangiota ~4,1 km
        self.assertEqual(delivery_fee_for("self", 100_000, lat=41.1905, lng=69.1381), 25_000 + 5 * 3_000)
        self.assertEqual(delivery_fee_for("self", 100_000, lat=41.3111, lng=69.2797), 25_000)

    def test_free_threshold_waives_only_the_base(self):
        self.assertEqual(delivery_fee_for("self", FREE_DELIVERY_FROM, lat=41.3111, lng=69.2797), 0)
        self.assertEqual(delivery_fee_for("self", FREE_DELIVERY_FROM, lat=41.1905, lng=69.1381), 15_000)

    def test_courier_range_and_unknown_location(self):
        self.assertTrue(z.courier_ok(41.4689, 69.5822))                       # Chirchiq ~11 km
        self.assertFalse(z.courier_ok(39.6542, 66.9597))                      # Samarqand
        self.assertEqual(delivery_fee_for("self", 100_000), 25_000)            # lokatsiyasiz — asosiy narx
        self.assertIsNone(z.km_outside(None, None))

    def test_buyer_sees_the_breakdown(self):
        self.assertEqual(z.breakdown_text(25_000, 41.1905, 69.1381, "uz"),
                         "📍 Shahardan 5 km tashqarida: 25 000 + 5 × 3 000 = 40 000 so'm")
        self.assertIn("км за городом", z.breakdown_text(25_000, 41.1905, 69.1381, "ru"))
        self.assertEqual(z.breakdown_text(25_000, 41.3111, 69.2797, "uz"), "")


if __name__ == "__main__":
    unittest.main()
