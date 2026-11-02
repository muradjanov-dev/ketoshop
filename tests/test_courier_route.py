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
from urllib.parse import parse_qs, urlsplit

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
        # no pin, delivered and cancelled stay out
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
        self.assertIn("Yandex Navigator’da ochish", html)
        self.assertIn("rtext=~41.310000,69.210000~40.330000,67.970000~41.311000,69.211000"
                      "~41.350000,69.300000&rtt=auto", html)
        self.assertIn("📦 BTS", html)                # a regional parcel says how it goes
        self.assertIn('data-route-move="2:-1"', html)
        self.assertEqual(self.r["num"], [[2, 1], [7, 2], [9, 3], [3, 4]])
        self.assertTrue(self.r["offLine"])        # no position → «📍 Aniqlash»

    def test_thirty_stops_have_one_complete_route_link(self):
        self.assertEqual(self.r["mainRouteLinks"], 1)
        self.assertEqual(self.r["legLinks"][0], 30)

    def test_all_active_statuses_are_included(self):
        self.assertEqual(self.r["active"], [21, 22, 23, 24, 25])

    def test_single_order_map_tap_opens_only_its_destination(self):
        self.assertTrue(self.r["singleTapPrevented"])
        url = urlsplit(self.r["singleTapOpened"])
        self.assertEqual(url.path, "/nav")
        params = parse_qs(url.query)
        self.assertEqual(params["p"], ["41.300000,69.200000"])
        self.assertEqual(params["from"], ["41.310000,69.278000"])

    def test_map_tab_tap_opens_the_complete_route_only_after_the_tap(self):
        self.assertEqual(self.r["openedBeforeTap"], 0)
        self.assertEqual(len(self.r["mapTapOpened"]), 1)
        url = urlsplit(self.r["mapTapOpened"][0])
        self.assertEqual(url.path, "/nav")
        params = parse_qs(url.query)
        self.assertEqual(len(params["p"][0].split("~")), 5)
        self.assertEqual(params["p"][0].split("~")[0], "41.311000,69.279000")
        self.assertEqual(params["from"], ["41.310000,69.278000"])
        self.assertEqual(self.r["emptyTapOpened"], 1)

    def test_first_map_tap_waits_for_location_before_nearest_order(self):
        self.assertEqual(self.r["delayedOpenedBeforePosition"], 0)
        self.assertTrue(self.r["delayedRequestedPosition"])
        params = parse_qs(urlsplit(self.r["delayedRoute"]).query)
        self.assertEqual(params["p"], ["41.350000,69.300000~41.310000,69.210000~41.300000,69.200000"])
        self.assertEqual(params["from"], ["41.351000,69.301000"])

    def test_browser_popup_preserves_tap_while_location_is_pending(self):
        self.assertEqual(self.r["reservedBeforePosition"], 1)
        self.assertIsNone(self.r["reservedOpener"])
        self.assertEqual(self.r["reservedRoute"], self.r["delayedRoute"])

    def test_location_timeout_and_popup_block_have_a_bounded_fallback(self):
        self.assertEqual(len(self.r["boundedFallback"]), 1)
        params = parse_qs(urlsplit(self.r["boundedFallback"][0]).query)
        self.assertEqual(len(params["p"][0].split("~")), 3)

    def test_complete_route_button_preserves_manual_order_without_waiting(self):
        self.assertEqual(self.r["manualRequestedPosition"], 0)
        params = parse_qs(urlsplit(self.r["manualRoute"]).query)
        self.assertEqual(params["p"], ["41.300000,69.200000~41.350000,69.300000~41.310000,69.210000"])

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
        params = parse_qs(urlsplit(self.r["appFromMe"]).query)
        self.assertEqual(params["from"], ["41.351000,69.301000"])
        self.assertEqual(params["p"], ["41.300000,69.200000~41.310000,69.210000"])

    def test_no_position_widget_starts_at_stop_one(self):
        self.assertEqual(self.r["widgetNoPos"],
                         "https://yandex.uz/map-widget/v1/?mode=routes&rtext="
                         "41.300000,69.200000~41.310000,69.210000&rtt=auto")


if __name__ == "__main__":
    unittest.main()
