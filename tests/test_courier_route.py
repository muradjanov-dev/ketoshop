"""Kuryer panelidagi marshrut (egasi, 2026-11-01).

Xarita/«Yo'l» bosilsa Yandex navigatsiya, hamma tayyor/yo'ldagi buyurtmalar
bitta marshrutda, kuryer tartibni o'zi o'zgartiradi. Kuryerning joylashuvi
ma'lum bo'lsa, marshrut va har bir havola shu joydan boshlanadi (kompyuterda
«Откуда» bo'sh qolmasin), «🛣 Yo'lni ko'rish» — Yandex vidjetida butun yo'l.
Kod webapp/admin.html ichida — node'da soxta doska va localStorage bilan
tekshiriladi (tests/courier_route_check.js).
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

    def test_all_ready_stops_longest_waiting_then_nearest(self):
        # every ready/shipped order with a pin, the BTS parcel too; pickup,
        # no pin, not-yet-ready and old 'preparing' stay out
        self.assertEqual(self.r["auto"], [1, 2, 3, 7])

    def test_single_stop_link_without_position_starts_empty(self):
        self.assertEqual(self.r["single"],
                         "https://yandex.uz/maps/?rtext=~41.300000,69.200000&rtt=auto")

    def test_courier_order_survives_refresh(self):
        self.assertEqual(self.r["moved"], [1, 3, 2, 7])
        self.assertTrue(self.r["manualAfterMove"])
        # delivered #1 drops off, new #9 joins after the last stop
        self.assertEqual(self.r["afterPoll"], [3, 2, 7, 9])

    def test_leave_out_and_bring_back(self):
        self.assertEqual(self.r["skipped"], [2, 7, 9])
        self.assertEqual(self.r["skippedList"], [3])
        self.assertEqual(self.r["readded"], [2, 7, 9, 3])

    def test_panel_and_numbered_pins(self):
        html = self.r["html"]
        self.assertFalse(self.r["hidden"])
        self.assertIn("Yandex’da yo’lga chiqish", html)
        self.assertIn("rtext=~41.310000,69.210000~40.330000,67.970000~41.311000,69.211000"
                      "~41.350000,69.300000&rtt=auto", html)
        self.assertIn("📦 BTS", html)                # a regional parcel says how it goes
        self.assertIn('data-route-move="2:-1"', html)
        self.assertEqual(self.r["num"], [[2, 1], [7, 2], [9, 3], [3, 4]])
        self.assertTrue(self.r["offLine"])        # no position → «📍 Aniqlash»

    def test_long_route_split_into_legs(self):
        self.assertEqual(self.r["legs"], ["🧭 1–10", "🧭 11–12"])
        self.assertEqual(self.r["legLinks"][:2], [10, 2])

    def test_no_stops_no_panel(self):
        self.assertTrue(self.r["emptyHidden"])

    def test_ready_but_nothing_to_drive_to_explains_instead_of_vanishing(self):
        self.assertFalse(self.r["noStopHidden"])
        self.assertIn("0 ta manzil", self.r["noStopHtml"])
        self.assertIn("1 tasi do’kondan olib ketiladi", self.r["noStopHtml"])
        self.assertIn("1 tasida xaritadagi nuqta (lokatsiya) yo’q", self.r["noStopHtml"])

    def test_known_position_is_the_start(self):
        # nearest to the courier first (#3), then nearest-next
        self.assertEqual(self.r["fromMe"], [3, 9, 2, 1])
        self.assertEqual(self.r["navFromMe"],
                         "https://yandex.uz/maps/?rtext=41.351000,69.301000~41.300000,69.200000&rtt=auto")
        self.assertEqual(self.r["widgetFromMe"],
                         "https://yandex.uz/map-widget/v1/?mode=routes&rtext="
                         "41.351000,69.301000~41.300000,69.200000~41.310000,69.210000&rtt=auto")
        self.assertTrue(self.r["posLine"])
        self.assertTrue(self.r["viewBtn"])
        # data-nav keeps only the stops — the start is added when the link is used
        self.assertRegex(self.r["navAttr"], r'^data-nav="\d+\.\d{6},\d+\.\d{6}(;\d+\.\d{6},\d+\.\d{6})*"$')
        self.assertNotIn("41.351000,69.301000", self.r["navAttr"])

    def test_no_position_widget_starts_at_stop_one(self):
        self.assertEqual(self.r["widgetNoPos"],
                         "https://yandex.uz/map-widget/v1/?mode=routes&rtext="
                         "41.300000,69.200000~41.310000,69.210000&rtt=auto")


if __name__ == "__main__":
    unittest.main()
