"""Kuryer panelidagi marshrut (egasi, 2026-11-01).

Xarita/«Yo'l» bosilsa Yandex navigatsiya (rtext=~… — boshlanish kuryerning
o'z joyi), hamma tayyor/yo'ldagi buyurtmalar bitta marshrutda, kuryer
tartibni o'zi o'zgartiradi. Kod webapp/admin.html ichida — node'da soxta
doska va localStorage bilan tekshiriladi (tests/courier_route_check.js).
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class CourierRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", str(ROOT / "tests" / "courier_route_check.js")],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_only_our_courier_stops_longest_waiting_then_nearest(self):
        # pickup, no pin, not-yet-ready, Yandex Taxi and old 'preparing' stay out
        self.assertEqual(self.r["auto"], [1, 2, 3])

    def test_single_stop_link_is_navigation_from_my_location(self):
        self.assertEqual(self.r["single"],
                         "https://yandex.uz/maps/?rtext=~41.300000,69.200000&rtt=auto")

    def test_courier_order_survives_refresh(self):
        self.assertEqual(self.r["moved"], [1, 3, 2])
        # delivered #1 drops off, new #9 joins after the last stop
        self.assertEqual(self.r["afterPoll"], [3, 2, 9])

    def test_leave_out_and_bring_back(self):
        self.assertEqual(self.r["skipped"], [2, 9])
        self.assertEqual(self.r["skippedList"], [3])
        self.assertEqual(self.r["readded"], [2, 9, 3])

    def test_panel_and_numbered_pins(self):
        html = self.r["html"]
        self.assertFalse(self.r["hidden"])
        self.assertIn("Yandex’da yo’lga chiqish", html)
        self.assertIn("rtext=~41.310000,69.210000~41.311000,69.211000~41.350000,69.300000&rtt=auto", html)
        self.assertIn('data-route-move="2:-1"', html)
        self.assertEqual(self.r["num"], [[2, 1], [9, 2], [3, 3]])

    def test_long_route_split_into_legs(self):
        self.assertEqual(self.r["legs"], ["🧭 1–10", "🧭 11–12"])
        self.assertEqual(self.r["legLinks"][:2], [10, 2])

    def test_no_stops_no_panel(self):
        self.assertTrue(self.r["emptyHidden"])


if __name__ == "__main__":
    unittest.main()
